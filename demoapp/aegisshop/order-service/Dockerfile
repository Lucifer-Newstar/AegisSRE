# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /build
COPY demoapp/aegisshop/order-service/requirements.txt .
COPY backend/libs/telemetry /tmp/telemetry
COPY demoapp/libs/fault-hooks /tmp/fault-hooks
RUN pip install --no-cache-dir "/tmp/telemetry[observability]" /tmp/fault-hooks -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    SERVICE_NAME=order-service \
    SERVICE_PORT=9003
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY demoapp/aegisshop/order-service/order_service ./order_service
EXPOSE 9003
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:9003/health', timeout=3).status==200 else 1)"
CMD ["python", "-m", "uvicorn", "order_service.main:app", "--host", "0.0.0.0", "--port", "9003"]
