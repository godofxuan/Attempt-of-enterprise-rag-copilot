# syntax=docker/dockerfile:1.7

FROM python:3.11.15-slim-bookworm@sha256:28255a3ace7eb4c48bc1b57b90af29e1bc82b4fd6c60614a8e3dce61b87ff941 AS dependencies

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 10001 rag \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin rag

WORKDIR /opt/rag
COPY requirements.txt /opt/rag/requirements.txt
RUN python -m pip install pip==26.0.1 \
    && python -m pip install --requirement /opt/rag/requirements.txt \
    && python -m pip check

FROM dependencies AS test
RUN apt-get update \
    && apt-get install --yes --no-install-recommends git \
    && git config --system --add safe.directory /workspace \
    && rm -rf /var/lib/apt/lists/*
COPY --chown=10001:10001 . /workspace
WORKDIR /workspace
USER 10001:10001
CMD ["python", "-m", "pytest", "-q"]

FROM dependencies AS runtime
COPY --chown=10001:10001 app /opt/rag/app
USER 10001:10001
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=10s --timeout=2s --start-period=10s --retries=6 \
    CMD ["python", "-c", "import json,urllib.request; response=urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=1); assert response.status == 200 and json.load(response).get('status') == 'alive'"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--workers", "1", "--no-access-log"]
