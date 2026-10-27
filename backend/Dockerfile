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

# Documentation only: the real listening port is read from $PORT at runtime
# (Render assigns it, default 10000; Compose leaves it unset -> 8000).
EXPOSE 8000

# 200 means schema applied and data available; 503 means it is not. Only a 200
# counts as healthy so `depends_on: condition: service_healthy` is meaningful.
# The probe reads $PORT itself so it follows the same assignment as the server.
HEALTHCHECK --interval=20s --timeout=6s --start-period=40s --retries=5 \
  CMD python -c "import os,urllib.request,sys; port=os.environ.get('PORT') or '8000'; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/api/health' % port, timeout=5).status == 200 else 1)"

# `sh -c` so ${PORT:-8000} is expanded at start-up (the JSON form alone never
# expands variables) and `exec` so uvicorn stays PID 1 and receives SIGTERM.
# --host 0.0.0.0 is mandatory: localhost/127.0.0.1 is unreachable from
# Render's port scan, the container network, and any external client.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
