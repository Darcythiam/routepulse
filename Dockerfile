FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
COPY templates ./templates
COPY static ./static
RUN useradd --system --uid 10001 routepulse
USER routepulse
EXPOSE 5000
CMD ["gunicorn", "--worker-class", "gthread", "--workers", "1", "--threads", "32", "--bind", "0.0.0.0:5000", "--access-logfile", "-", "app:app"]
