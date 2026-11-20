FROM python:3.13.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/db/migrations
COPY db/migrations/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock
COPY db/migrations/ ./

CMD ["python", "apply_migrations.py"]
