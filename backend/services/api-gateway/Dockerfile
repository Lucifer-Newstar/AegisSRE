# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
WORKDIR /build
COPY backend/services/api-gateway/requirements-runtime.lock ./requirements-runtime.lock
RUN pip install --no-cache-dir -r requirements-runtime.lock
COPY backend/services/api-gateway /build/gateway
RUN pip install --no-cache-dir --no-deps /build/gateway

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=10 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2).close()"
CMD ["python", "-m", "uvicorn", "api_gateway.main:create_app", "--factory", "--no-proxy-headers", "--host", "0.0.0.0", "--port", "8000"]
