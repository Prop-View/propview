FROM python:3.13.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/services/data-retention
COPY services/data-retention/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock
COPY services/data-retention/ ./
COPY services/tool-router/ /app/services/tool-router/
COPY services/orchestrator/tenant_registry.py /app/services/orchestrator/tenant_registry.py

CMD ["python", "retention_scan.py"]
