# SpriteKiln — CPU-only image (API + prebuilt web UI).
# GPU workloads (ComfyUI / Pixal3D) run outside this container and are reached over HTTP.
FROM node:20-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    SPRITEKILN_DATA=/app/data
WORKDIR /app

# ffmpeg is used by PyAV for mp4 export; libgl/libglib back Pillow and 3D previews
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/
COPY mcp/ mcp/
COPY skills/ skills/
COPY --from=web /web/dist web/dist
COPY README.md LICENSE ./
RUN mkdir -p /app/data

EXPOSE 7788
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7788/api/system', timeout=4)"
CMD ["python", "backend/run.py", "--host", "0.0.0.0", "--port", "7788"]
