
import os
import subprocess
import tempfile
import torch
from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse
from transformers import pipeline, AutoModelForSpeechSeq2Seq, AutoProcessor
from moviepy.editor import VideoFileClip
from datetime import timedelta
from deep_translator import GoogleTranslator

# إنشاء تطبيق FastAPI
app = FastAPI()

# دالة تحويل الوقت
def format_time(seconds):
    td = timedelta(seconds=seconds)
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = td.microseconds // 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

# استخراج الصوت من الفيديو
def extract_audio(video_path):
    temp_dir = tempfile.gettempdir()
    audio_path = os.path.join(temp_dir, "extracted_audio.wav")

    video_clip = VideoFileClip(video_path)
    video_clip.audio.write_audiofile(audio_path, codec='pcm_s16le')
    video_clip.close()

    return audio_path, video_clip.duration

# تحويل الصوت إلى نص
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

# الترجمة من الإنجليزية إلى العربية
def translate_text(text):
    translator = GoogleTranslator(source='en', target='ar')
    return translator.translate(text)

# إنشاء ملف SRT من المقاطع المترجمة
def create_srt(segments, output_path):
    with open(output_path, 'w', encoding='utf-8-sig') as srt_file:
        for i, segment in enumerate(segments, start=1):
            start_time = segment.get('start', 0)
            end_time = segment.get('end', 0)
            text = segment.get('text', '')
            translation = segment.get('translation', '')
            srt_file.write(f"{i}
")
            srt_file.write(f"{format_time(start_time)} --> {format_time(end_time)}
")
            srt_file.write(f"{translation}

")

# حرق الترجمات على الفيديو
def burn_subtitles(video_path, srt_path, output_path):
    font_path = "/usr/share/fonts/truetype/Amiri-Regular.ttf"
    cmd = [
        'ffmpeg', '-y', '-i', video_path,
        '-vf', f"subtitles='{srt_path}':force_style='FontName={font_path},FontSize=24,PrimaryColour=&HFFFFFF,OutlineColour=&H000000,BorderStyle=3,Alignment=2,Encoding=1'",
        '-sub_charenc', 'UTF-8',
        '-c:v', 'libx264', '-crf', '18',
        '-c:a', 'copy',
        output_path
    ]
    subprocess.run(cmd, check=True)
    return output_path

# معالجة الفيديو بالكامل
def process_video(video_path):
    temp_dir = tempfile.gettempdir()
    file_name = os.path.splitext(os.path.basename(video_path))[0]

    audio_path, duration = extract_audio(video_path)
    segments = transcribe_audio(audio_path)

    translated_segments = []
    for segment in segments:
        text = segment['text'] if hasattr(segment, 'get') else segment.text
        translated_text = translate_text(text)
        segment['translation'] = translated_text
        translated_segments.append(segment)

    srt_path = os.path.join(temp_dir, f"{file_name}.srt")
    create_srt(translated_segments, srt_path)

    output_path = os.path.join(temp_dir, f"{file_name}_translated.mp4")
    burn_subtitles(video_path, srt_path, output_path)

    return output_path, srt_path

# endpoint لتحميل الفيديو ومعالجته
@app.post("/process_video/")
async def process_video_endpoint(file: UploadFile = File(...)):
    # حفظ الفيديو مؤقتًا
    video_path = os.path.join(tempfile.gettempdir(), file.filename)
    with open(video_path, "wb") as f:
        f.write(await file.read())

    # معالجة الفيديو
    result_path, srt_path = process_video(video_path)

    # إرجاع الفيديو المترجم وملف SRT
    return {
        "video": FileResponse(result_path),
        "srt": FileResponse(srt_path)
    }

# تشغيل التطبيق
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
