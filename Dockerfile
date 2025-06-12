FROM python:3.10-slim

# إعداد بيئة العمل
WORKDIR /app

# نسخ الملفات
COPY . /app

# تثبيت المتطلبات
RUN pip install --no-cache-dir -r requirements.txt

# إنشاء مجلد الإخراج لو مش موجود
RUN mkdir -p output

# إعطاء صلاحيات تنفيذ للـ startup script
RUN chmod +x startup.sh

# فتح البورت
EXPOSE 8000

# أمر التشغيل الافتراضي
CMD ["./startup.sh"]
