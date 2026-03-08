FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      libxml2-dev libxslt1-dev \
      && \
    rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /data/repo

ENV REPOMANCER_HOST=0.0.0.0 \
    REPOMANCER_PORT=8000 \
    REPOMANCER_DB_PATH=/data/repomancer.db \
    REPOMANCER_DOWNLOAD_DIR=/data/repo \
    REPOMANCER_USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0" \
    REPOMANCER_REFERRER="" \
    REPOMANCER_PAGE_SIZE=15 \
    REPOMANCER_UPDATE_INTERVAL_MINUTES=0 \
    REPOMANCER_REQUEST_TIMEOUT=15 \
    REPOMANCER_SECRET_KEY=change-me

EXPOSE 8000

CMD ["python", "manage.py", "runserver"]
