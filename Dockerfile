# استخدم Python الرسمي وخفيف
FROM python:3.10-slim

# تثبيت الأدوات اللازمة
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    libsm6 \
    libxext6 \
    libgl1 \
 && rm -rf /var/lib/apt/lists/*

# تعيين مجلد العمل داخل الكونتينر
WORKDIR /app

# نسخ ملفات المشروع داخل الكونتينر
COPY . .

# تثبيت المتطلبات من requirements.txt
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# إنشاء مجلد output داخل الكونتينر (علشان ميحصلش crash)
RUN mkdir -p /app/output

# فتح البورت 8000 لتشغيل التطبيق
EXPOSE 8000

# أمر التشغيل لما الكونتينر يبدأ
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
