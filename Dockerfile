# HeatShield API — single-process image, no build steps that need the network.
#
#   docker build -t heatshield-api .
#   docker run --rm -p 8000:8000 heatshield-api     # docs at :8000/docs
#
# The image ships the committed forecast cache and processed tables so the
# container serves real numbers on its first request with no network at all.
# Refresh inside the container with:  docker exec <id> python -m scripts.refresh
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HS_TIMEZONE=Asia/Kolkata \
    PORT=8000

WORKDIR /app

# Dependencies first: the layer is cached across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY core/ ./core/
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY data/ ./data/

# Run unprivileged. Nothing in the pipeline needs root.
RUN useradd --create-home --shell /bin/bash heatshield \
    && mkdir -p /app/data/processed /app/data/cache /app/logs \
    && chown -R heatshield:heatshield /app
USER heatshield

EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
