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

# Deliberately no ENV for the tuneables: real environment variables outrank
# .env, so baking values here would silently ignore the mounted settings file.
# app/config.py holds the defaults, .env overrides them.
# PORT is the exception — the CMD needs it before the app can read anything,
# so the container always listens on 8000 and the host side is mapped in
# compose. Changing PORT in .env moves the *host* port, not this one.
ENV PORT=8000

EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
