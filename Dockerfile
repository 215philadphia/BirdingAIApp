FROM python:3.13-slim

# ffmpeg converts iPhone Voice Memos (.m4a) and other formats BirdNET can't read directly.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download the BirdNET models at build time so the server starts ready.
RUN python -c "import birdnet; birdnet.load('acoustic', '2.4', 'tf', library='litert'); birdnet.load('geo', '2.4', 'tf', library='litert')"

COPY app ./app

# Recordings and the SQLite database. Mount a persistent disk here.
ENV DATA_DIR=/data
VOLUME /data

EXPOSE 8000
# Hosting platforms set $PORT and terminate HTTPS in front of the app.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
