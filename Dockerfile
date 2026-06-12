# Stage 1: build the frontend
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# vite.config.js outputs to ../backend/static; redirect inside the container
RUN npx vite build --outDir /build/dist --emptyOutDir

# Stage 2: runtime
FROM python:3.12-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    # Headless Chromium + system libs for the browser-sniffing fallback
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

COPY backend/app ./app
COPY --from=frontend /build/dist ./static

ENV TMP_DIR=/tmp/neko_dl \
    MAX_CONCURRENT=2 \
    MAX_QUEUE_SIZE=50 \
    FILE_TTL_SECONDS=1800 \
    PORT=8000

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
