FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY signer ./signer
RUN cd /srv/signer \
    && node fetch-sdk.js \
    && npm install --omit=dev --no-audit --no-fund \
    && node -e "require('jsdom'); console.log('jsdom ok')"
RUN mkdir -p /tmp/douyin-dl /data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
