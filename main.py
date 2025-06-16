import os
import uuid
import subprocess
import tempfile
from datetime import timedelta
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from moviepy.editor import VideoFileClip
from deep_translator import GoogleTranslator
import whisper

app = FastAPI()

def format_time(seconds):
    td = timedelta(seconds=seconds)
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = td.microseconds // 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

def extract_audio(video_path):
    temp_dir = tempfile.gettempdir()
    audio_path = os.path.join(temp_dir, f"audio_{uuid.uuid4().hex}.wav")
    video_clip = VideoFileClip(video_path)
    video_clip.audio.write_audiofile(audio_path, codec='pcm_s16le')
    duration = video_clip.duration
    video_clip.close()
    return audio_path, duration

def transcribe_audio(audio_path):
    try:
        model = whisper.load_model("base")
        result = model.transcribe(audio_path, word_timestamps=True)
        return result["segments"]
    except Exception as e:
        print(f"حدث خطأ في التحويل الصوتي: {e}")
        raise

def translate_text(text):
    translator = GoogleTranslator(source='en', target='ar')
    return translator.translate(text)

def create_srt(segments, output_path):
    with open(output_path, 'w', encoding='utf-8-sig') as srt_file:
        for i, segment in enumerate(segments, start=1):
            start_time = segment['start']
            end_time = segment['end']
            text = segment.get('text', '')
            translation = translate_text(text)
            srt_file.write(f"{i}\n")
            srt_file.write(f"{format_time(start_time)} --> {format_time(end_time)}\n")
            srt_file.write(f"{translation}\n\n")

def burn_subtitles(video_path, srt_path, output_path):
    # استخدام خط DejaVu Sans المتوفر افتراضيًا
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    cmd = [
        'ffmpeg', '-y', '-i', video_path,
        '-vf', f"subtitles='{srt_path}':fontsdir='/usr/share/fonts/truetype/':force_style='FontName=DejaVu Sans,FontSize=24,MarginV=30,PrimaryColour=&H00FFFF,Outline=1,Shadow=0,BorderStyle=4,Alignment=2,Encoding=1'",
        '-c:v', 'libx264', '-crf', '18',
        '-c:a', 'copy',
        output_path
    ]
    try:
        result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("FFmpeg Output:", result.stdout.decode())
        print("FFmpeg Errors:", result.stderr.decode())
    except subprocess.CalledProcessError as e:
        print("FFmpeg Error:", e.stderr.decode())
        raise RuntimeError(f"FFmpeg failed: {e.stderr.decode()}")
    return output_path

def process_video(video_path):
    temp_dir = tempfile.gettempdir()
    file_name = os.path.splitext(os.path.basename(video_path))[0]
    unique_id = str(uuid.uuid4())[:8]

    audio_path, duration = extract_audio(video_path)
    segments = transcribe_audio(audio_path)

    srt_path = os.path.join(temp_dir, f"{file_name}_{unique_id}.srt")
    create_srt(segments, srt_path)

    output_path = os.path.join(temp_dir, f"{file_name}_{unique_id}_translated.mp4")
    burn_subtitles(video_path, srt_path, output_path)

    if not os.path.exists(output_path):
        raise RuntimeError("فشل في إنشاء الفيديو المترجم. تحقق من سجل FFmpeg.")
    return output_path

@app.post("/process_video/")
async def process_video_endpoint(file: UploadFile = File(...)):
    video_path = None
    result_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as temp_video:
            video_path = temp_video.name
            content = await file.read()
            temp_video.write(content)
        
        result_path = process_video(video_path)
        
        if not os.path.exists(result_path):
            raise HTTPException(status_code=500, detail="فشل في إنشاء الفيديو المترجم.")
            
        return FileResponse(result_path, media_type="video/mp4", filename="translated.mp4")
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"خطأ داخلي: {str(e)}")
    
    finally:
        if video_path and os.path.exists(video_path):
            os.unlink(video_path)
        if result_path and os.path.exists(result_path):
            os.unlink(result_path)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
