FROM python:3.13.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/services/orchestrator
COPY services/orchestrator/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock
# presidio's analyzer loads this spaCy model lazily on the first mask_pii()
# call (services/compliance/pii_masking.py). It is published as a GitHub
# release asset, not on PyPI, so it cannot live in the hash-pinned lock --
# without this step the image installs cleanly and then fails at runtime on
# the first call transcript it tries to persist.
RUN python -m spacy download en_core_web_sm
COPY services/ /app/services/

EXPOSE 9090
CMD ["python", "worker_entrypoint.py", "start"]
