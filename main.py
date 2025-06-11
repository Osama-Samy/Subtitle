import os
import subprocess
import tempfile
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from transformers import pipeline, AutoModelForSpeechSeq2Seq, AutoProcessor
import torch
from moviepy.editor import VideoFileClip
from datetime import timedelta
from deep_translator import GoogleTranslator

app = FastAPI(title="Video Subtitle Translator")

def format_time(seconds):
    td = timedelta(seconds=seconds)
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = td.microseconds // 1000
    return f"{hours:02d}:{minutes:02d},{seconds:03d}"

def extract_audio(video_path):
    temp_dir = tempfile.gettempdir()
    audio_path = os.path.join(temp_dir, "extracted_audio.wav")
    video_clip = VideoFileClip(video_path)
    video_clip.audio.write_audiofile(audio_path, codec='pcm_s16le')
    duration = video_clip.duration
    video_clip.close()
    return audio_path, duration

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
        print(f"حدث خطأ أثناء استخدام نموذج fractalego: {e}")
        import whisper
        model = whisper.load_model("base")
        result = model.transcribe(audio_path, word_timestamps=True)
        return result["segments"]

def translate_text(text):
    translator = GoogleTranslator(source='en', target='ar')
    return translator.translate(text)

def create_srt(segments, output_path):
    with open(output_path, 'w', encoding='utf-8-sig') as srt_file:
        for i, segment in enumerate(segments, start=1):
            if hasattr(segment, 'get'):
                start_time = segment.get('start', 0)
                end_time = segment.get('end', 0)
                text = segment.get('text', '')
                translation = segment.get('translation', '')
            else:
                start_time = segment.start
                end_time = segment.end
                text = segment.text
                translation = getattr(segment, 'translation', text)
            srt_file.write(f"{i}\n")
            srt_file.write(f"{format_time(start_time)} --> {format_time(end_time)}\n")
            srt_file.write(f"{translation}\n\n")

@app.post("/translate/")
async def translate_video(file: UploadFile = File(...)):
    # حفظ الفيديو مؤقتًا
    temp_dir = tempfile.gettempdir()
    video_path = os.path.join(temp_dir, file.filename)
    with open(video_path, "wb") as f:
        f.write(await file.read())

    try:
        audio_path, duration = extract_audio(video_path)
        segments = transcribe_audio(audio_path)
        translated_segments = []
        for segment in segments:
            if hasattr(segment, 'get'):
                text = segment.get('text', '')
                translated_text = translate_text(text)
                segment['translation'] = translated_text
            else:
                text = segment.text
                segment.translation = translate_text(text)
            translated_segments.append(segment)
        srt_path = os.path.join(temp_dir, f"{os.path.splitext(file.filename)[0]}.srt")
        create_srt(translated_segments, srt_path)
        return FileResponse(srt_path, media_type="application/x-subrip", filename="translated.srt")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # تنظيف الملفات المؤقتة
        try:
            if os.path.exists(video_path):
                os.remove(video_path)
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except:
            pass

@app.get("/")
def root():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
