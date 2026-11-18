FROM python:3.13.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/services/follow-up-manager
COPY services/follow-up-manager/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock
COPY services/follow-up-manager/ ./
COPY services/tool-router/ /app/services/tool-router/
COPY services/orchestrator/tenant_registry.py /app/services/orchestrator/tenant_registry.py
COPY services/orchestrator/tenant_settings.py /app/services/orchestrator/tenant_settings.py
COPY services/scheduling/ /app/services/scheduling/

CMD ["python", "followup_scan.py"]
