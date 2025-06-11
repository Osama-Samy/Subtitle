import os
import tempfile
import shutil
import uuid
from datetime import timedelta
import logging
from typing import Optional
import urllib.parse

from fastapi import FastAPI, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from pydantic import BaseModel

from moviepy.editor import VideoFileClip
import whisper
from deep_translator import GoogleTranslator
import subprocess

# إعداد اللوجينج
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# إعداد التطبيق
app = FastAPI(
    title="Arabic Video Subtitle API",
    description="API for adding Arabic subtitles to English videos",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMP_DIR = os.path.join(tempfile.gettempdir(), "subtitle_api")
os.makedirs(TEMP_DIR, exist_ok=True)

OUTPUT_DIR = os.path.join(os.getcwd(), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

BASE_URL = "https://your-app-name.azurewebsites.net"  # عدّل هذا بعد النشر

MODEL_SIZE = "base"
logger.info(f"Loading Whisper model: {MODEL_SIZE}")
model = whisper.load_model(MODEL_SIZE)
logger.info("Whisper model loaded successfully")

def clean_filename(filename):
    cleaned = filename.replace(' ', '_')
    cleaned = ''.join(c for c in cleaned if c.isalnum() or c in '_-.')
    return cleaned

def format_time(seconds):
    try:
        seconds = float(seconds)
        if seconds < 0:
            seconds = 0
        td = timedelta(seconds=seconds)
        total_seconds = int(td.total_seconds())
        milliseconds = int(td.microseconds / 1000)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"
    except Exception as e:
        logger.error(f"Error formatting time for seconds={seconds}: {e}")
        return "00:00:00,000"

def extract_audio(video_path):
    logger.info(f"Extracting audio from: {video_path}")
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    audio_path = os.path.join(TEMP_DIR, f"{base_name}_extracted_audio.wav")
    duration = 0
    try:
        video_clip = VideoFileClip(video_path)
        duration = video_clip.duration
        logger.info(f"Video duration: {duration} seconds")
        video_clip.audio.write_audiofile(audio_path, codec='pcm_s16le', logger='bar')
        video_clip.close()
        logger.info(f"Audio extracted successfully to: {audio_path}")
        return audio_path, duration
    except Exception as e:
        logger.error(f"Error extracting audio: {e}", exc_info=True)
        if 'video_clip' in locals() and video_clip:
            try:
                video_clip.close()
            except Exception as close_err:
                logger.error(f"Error closing video clip: {close_err}")
        return None, 0

def transcribe_audio(audio_path):
    logger.info(f"Transcribing audio file: {audio_path}")
    try:
        result = model.transcribe(audio_path, word_timestamps=False)
        logger.info("Transcription complete.")
        return result["segments"]
    except Exception as e:
        logger.error(f"Error during transcription: {e}", exc_info=True)
        return []

def translate_text(text, target_language='ar'):
    if not text or not isinstance(text, str):
        return ""
    try:
        translator = GoogleTranslator(source='auto', target=target_language)
        translation = translator.translate(text)
        return translation if translation else ""
    except Exception as e:
        logger.error(f"Error translating text: {e}", exc_info=True)
        return text

def create_srt(segments, output_path):
    logger.info(f"Creating SRT file: {output_path}")
    try:
        with open(output_path, 'w', encoding='utf-8-sig') as srt_file:
            count = 1
            for segment in segments:
                start_time = segment.get('start')
                end_time = segment.get('end')
                original_text = segment.get('text', '').strip()
                
                if start_time is None or end_time is None:
                    logger.warning(f"Skipping segment due to missing time data: {original_text}")
                    continue
                    
                translated_text = translate_text(original_text)
                if not translated_text:
                    logger.warning(f"Skipping segment due to empty translation: {original_text}")
                    continue

                start_formatted = format_time(start_time)
                end_formatted = format_time(end_time)

                srt_file.write(f"{count}\n")
                srt_file.write(f"{start_formatted} --> {end_formatted}\n")
                srt_file.write(f"{translated_text}\n\n")
                count += 1
        logger.info("SRT file created successfully.")
        return output_path
    except Exception as e:
        logger.error(f"Error creating SRT file: {e}", exc_info=True)
        return None

def burn_subtitles(video_path, srt_path, output_path):
    logger.info(f"Burning subtitles from {srt_path} into {video_path}")
    font_path = "/usr/share/fonts/truetype/Amiri-Regular.ttf"
    cmd = [
        'ffmpeg', 
        '-y',
        '-i', video_path,
        '-vf', f"subtitles='{srt_path}':force_style='FontName={font_path},FontSize=24,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BorderStyle=3,Alignment=2'",
        '-c:v', 'libx264', 
        '-crf', '23', 
        '-preset', 'fast', 
        '-c:a', 'aac', 
        '-b:a', '128k', 
        output_path
    ]
    logger.info(f"Running FFmpeg command: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8')
        logger.info("FFmpeg finished successfully.")
        logger.debug(f"FFmpeg stdout:\n{result.stdout}")
        logger.debug(f"FFmpeg stderr:\n{result.stderr}")
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error (return code {e.returncode}): {e}")
        logger.error(f"FFmpeg stdout:\n{e.stdout}")
        logger.error(f"FFmpeg stderr:\n{e.stderr}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred during subtitle burning: {e}", exc_info=True)
        return None

def cleanup_files(file_paths):
    for file_path in file_paths:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Removed temporary file: {file_path}")
            except Exception as e:
                logger.warning(f"Could not remove file {file_path}: {e}")

def get_full_url(path):
    if path.startswith('/'):
        path = path[1:]
    path_parts = path.split('/')
    encoded_parts = [urllib.parse.quote(part) for part in path_parts]
    encoded_path = '/'.join(encoded_parts)
    return f"{BASE_URL}/{encoded_path}"

class SubtitleResponse(BaseModel):
    message: str
    video_url: Optional[str] = None
    srt_url: Optional[str] = None
    error: Optional[str] = None

@app.post("/subtitle/", response_model=SubtitleResponse)
async def create_subtitle(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    return_srt: bool = Form(True),
    return_video: bool = Form(True)
):
    if not video.filename:
        raise HTTPException(status_code=400, detail="No video file provided")
    job_id = str(uuid.uuid4())
    clean_video_filename = clean_filename(video.filename)
    video_filename = f"{job_id}_{clean_video_filename}"
    video_path = os.path.join(TEMP_DIR, video_filename)
    try:
        with open(video_path, "wb") as buffer:
            shutil.copyfileobj(video.file, buffer)
    except Exception as e:
        logger.error(f"Error saving uploaded video: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving video: {str(e)}")
    base_name = os.path.splitext(video_filename)[0]
    srt_path = os.path.join(OUTPUT_DIR, f"{base_name}.srt")
    output_video_path = os.path.join(OUTPUT_DIR, f"{base_name}_subtitled.mp4")
    try:
        audio_path, duration = extract_audio(video_path)
        if not audio_path or duration == 0:
            raise HTTPException(status_code=500, detail="Failed to extract audio from video")
        segments = transcribe_audio(audio_path)
        if not segments:
            raise HTTPException(status_code=500, detail="Failed to transcribe audio")
        srt_file_path = create_srt(segments, srt_path)
        if not srt_file_path:
            raise HTTPException(status_code=500, detail="Failed to create SRT file")
        video_file_path = None
        if return_video:
            video_file_path = burn_subtitles(video_path, srt_file_path, output_video_path)
            if not video_file_path:
                raise HTTPException(status_code=500, detail="Failed to burn subtitles into video")
        temp_files = [video_path, audio_path]
        background_tasks.add_task(cleanup_files, temp_files)
        response = {
            "message": "Processing completed successfully",
            "srt_url": get_full_url(f"download/srt/{os.path.basename(srt_path)}") if return_srt else None,
            "video_url": get_full_url(f"download/video/{os.path.basename(output_video_path)}") if return_video else None
        }
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing video: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing video: {str(e)}")

@app.get("/download/srt/{filename}")
async def download_srt(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="SRT file not found")
    return FileResponse(file_path, media_type="application/x-subrip", filename=filename)

@app.get("/download/video/{filename}")
async def download_video(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Video file not found")
    return FileResponse(
        path=file_path,
        media_type="video/mp4",
        filename=filename,
        headers={"Content-Disposition": "inline"}
    )

@app.get("/health")
async def health_check():
    return {"status": "healthy", "model": MODEL_SIZE}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=False)
