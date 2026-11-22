# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /build
COPY backend/services/registry-service/requirements.txt .
COPY backend/libs/storage /tmp/storage
COPY backend/libs/security /tmp/security
COPY backend/libs/telemetry /tmp/telemetry
RUN pip install --no-cache-dir "/tmp/telemetry[observability]" /tmp/storage /tmp/security -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    SERVICE_NAME=registry-service \
    SERVICE_PORT=8101
WORKDIR /app
ENV DATABASE_URL=sqlite:////data/aegis-metadata.db
RUN mkdir /data && chown 10001:10001 /data
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY backend/services/registry-service/registry_service ./registry_service
USER 10001:10001
EXPOSE 8101
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8101/health', timeout=3).status==200 else 1)"
CMD ["python", "-m", "uvicorn", "registry_service.main:app", "--host", "0.0.0.0", "--port", "8101"]
