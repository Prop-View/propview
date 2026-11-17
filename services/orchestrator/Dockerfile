FROM python:3.13.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/services/orchestrator
COPY services/orchestrator/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock
COPY services/ /app/services/

EXPOSE 9090
CMD ["python", "worker_entrypoint.py", "start"]
