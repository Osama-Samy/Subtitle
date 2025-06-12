import os
import tempfile
import torch
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from transformers import pipeline, AutoModelForSpeechSeq2Seq, AutoProcessor
from moviepy.editor import VideoFileClip
from datetime import timedelta
from deep_translator import GoogleTranslator
import subprocess

app = FastAPI(title="Video Subtitle Translator")

def format_time(seconds):
    td = timedelta(seconds=seconds)
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = td.microseconds // 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

def extract_audio(video_path):
    try:
        temp_dir = tempfile.gettempdir()
        audio_path = os.path.join(temp_dir, "extracted_audio.wav")
        video_clip = VideoFileClip(video_path)
        video_clip.audio.write_audiofile(audio_path, codec='pcm_s16le')
        duration = video_clip.duration
        video_clip.close()
        return audio_path, duration
    except Exception as e:
        raise RuntimeError(f"فشل في استخراج الصوت: {e}")

def transcribe_audio(audio_path):
    try:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model_id = "fractalego/personal-speech-to-text-model"
        model = AutoModelForSpeechSeq2Seq.from_pretrained(model_id)
        processor = AutoProcessor.from_pretrained(model_id)
        model.to(device)
        pipe = pipeline(
            "automatic-speech-recognition",
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            max_new_tokens=128,
            chunk_length_s=30,
            batch_size=16,
            return_timestamps=True,
            device=device,
        )
        result = pipe(audio_path)
        return result["chunks"]
    except Exception as e:
        try:
            import whisper
            model = whisper.load_model("base")
            result = model.transcribe(audio_path, word_timestamps=True)
            return result["segments"]
        except Exception as whisper_error:
            raise RuntimeError(f"فشل استخدام Whisper أو HuggingFace model: {whisper_error}")

def translate_text(text):
    try:
        translator = GoogleTranslator(source='en', target='ar')
        return translator.translate(text)
    except Exception as e:
        raise RuntimeError(f"فشل في الترجمة: {e}")

def create_srt(segments, output_path):
    try:
        with open(output_path, 'w', encoding='utf-8-sig') as srt_file:
            for i, segment in enumerate(segments, start=1):
                start_time = segment.get('start', 0)
                end_time = segment.get('end', 0)
                translation = segment.get('translation', '')
                srt_file.write(f"{i}\n")
                srt_file.write(f"{format_time(start_time)} --> {format_time(end_time)}\n")
                srt_file.write(f"{translation}\n\n")
    except Exception as e:
        raise RuntimeError(f"فشل في إنشاء ملف الترجمة SRT: {e}")

def burn_subtitles(video_path, srt_path, output_path):
    try:
        cmd = [
            'ffmpeg', '-y', '-i', video_path,
            '-vf', f"subtitles={srt_path}:force_style='FontName=Arial,FontSize=24'",
            '-c:v', 'libx264', '-crf', '18',
            '-c:a', 'copy',
            output_path
        ]
        subprocess.run(cmd, check=True)
        return output_path
    except Exception as e:
        raise RuntimeError(f"فشل في دمج الترجمة مع الفيديو: {e}")

@app.post("/translate/")
async def translate_video(file: UploadFile = File(...)):
    temp_dir = tempfile.gettempdir()
    video_path = os.path.join(temp_dir, file.filename)

    try:
        with open(video_path, "wb") as f:
            f.write(await file.read())

        audio_path, duration = extract_audio(video_path)
        segments = transcribe_audio(audio_path)

        translated_segments = []
        for segment in segments:
            text = segment['text'] if isinstance(segment, dict) else getattr(segment, 'text', '')
            translated_text = translate_text(text)
            segment['translation'] = translated_text
            translated_segments.append(segment)

        srt_path = os.path.join(temp_dir, f"{os.path.splitext(file.filename)[0]}.srt")
        create_srt(translated_segments, srt_path)

        output_video_path = os.path.join(temp_dir, f"{os.path.splitext(file.filename)[0]}_ar.mp4")
        burn_subtitles(video_path, srt_path, output_video_path)

        return FileResponse(output_video_path, media_type="video/mp4", filename="video_with_arabic_subtitle.mp4")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
            if 'audio_path' in locals() and os.path.exists(audio_path):
                os.remove(audio_path)
            if 'srt_path' in locals() and os.path.exists(srt_path):
                os.remove(srt_path)
        except:
            pass

@app.get("/")
def root():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
