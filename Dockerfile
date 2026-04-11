FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /var/data/uploads/images
RUN mkdir -p /var/data/uploads/videos

ENV PORT=10000

CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120