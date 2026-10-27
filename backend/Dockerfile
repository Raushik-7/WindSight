FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Absolute path so the SQLite file lives on the mounted volume, never on the
    # container's ephemeral layer. Compose overrides this; it is also the safe
    # default when the image is run directly.
    DATABASE_URL=sqlite:////app/data/windsight.db

WORKDIR /app

# Dependencies first so application code changes do not invalidate the layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Non-root runtime user, created before the data directory so ownership sticks.
RUN addgroup --system app && adduser --system --ingroup app app

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
# Committed real-data snapshots: let a fresh volume seed itself offline.
COPY data ./data

# The database and upstream cache both live under /app/data, which Compose
# mounts as a named volume. Ownership is copied into a newly created volume.
RUN mkdir -p /app/data/cache && chown -R app:app /app/data

USER app

EXPOSE 8000

# 200 means schema applied and data available; 503 means it is not. Only a 200
# counts as healthy so `depends_on: condition: service_healthy` is meaningful.
HEALTHCHECK --interval=20s --timeout=6s --start-period=40s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
