# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /build
COPY infra/kind/ci-versions.json /build/kubernetes-tools.json
# The executor is opt-in and needs an explicitly provisioned scoped kubeconfig.
# Ship the exact checksum-verified kubectl used in the owned integration gate.
RUN python -c 'import hashlib,json,pathlib,urllib.request; p=json.loads(pathlib.Path("/build/kubernetes-tools.json").read_text()); data=urllib.request.urlopen(p["kubectl_url"],timeout=60).read(); assert hashlib.sha256(data).hexdigest()==p["kubectl_sha256"]; dest=pathlib.Path("/usr/local/bin/kubectl"); dest.write_bytes(data); dest.chmod(0o755)'
COPY backend/services/incidents-service/requirements-runtime.lock ./requirements-runtime.lock
RUN pip install --no-cache-dir -r requirements-runtime.lock
COPY backend/libs/telemetry /build/telemetry
COPY backend/libs/eventbus /build/eventbus
COPY backend/services/incidents-service /build/incidents
RUN pip install --no-cache-dir --no-deps /build/telemetry /build/eventbus /build/incidents

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    AEGIS_DATABASE_URL=sqlite:////data/aegis-incidents.db
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin/kubectl /usr/local/bin/kubectl
RUN mkdir /data && chown 10001:10001 /data
USER 10001:10001
EXPOSE 8201
HEALTHCHECK --interval=10s --timeout=3s --retries=10 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8201/health', timeout=2).close()"
CMD ["python", "-m", "uvicorn", "incidents_service.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8201"]
