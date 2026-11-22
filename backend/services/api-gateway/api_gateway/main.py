"""Authenticated fixed-route gateway with distributed bounded rate limits."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from http.cookiejar import DefaultCookiePolicy
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis import Redis
from redis.exceptions import RedisError

from api_gateway.config import Settings
from api_gateway.routes import ROUTES, Route

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}")
REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
PREFIX = "/api/v1"
bearer = HTTPBearer(auto_error=False)


class NoCookies(DefaultCookiePolicy):
    def set_ok(self, cookie: Any, request: Any) -> bool:
        return False


class RateGate:
    def __init__(self, client: Redis):
        self.client = client

    def consume(self, principal: str, limit: int) -> tuple[bool, int]:
        key = "aegis:gateway:rate:" + hashlib.sha256(principal.encode()).hexdigest()
        # Atomic INCR + EXPIRE NX, using the Redis server's expiry clock. The
        # window never extends on each request and cannot be left without TTL.
        with self.client.pipeline(transaction=True) as pipeline:
            pipeline.incr(key)
            pipeline.expire(key, 60, nx=True)
            pipeline.ttl(key)
            count, _, ttl = pipeline.execute()
        return int(count) <= limit, max(1, int(ttl))


def create_app(
    settings: Settings | None = None,
    *,
    http: httpx.AsyncClient | None = None,
    redis_client: Redis | None = None,
) -> FastAPI:
    config = settings or Settings()
    upstream = http or httpx.AsyncClient(
        timeout=httpx.Timeout(5, connect=3),
        trust_env=False,
        follow_redirects=False,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    upstream.cookies.clear()
    upstream.cookies.jar.set_policy(NoCookies())
    redis = redis_client or Redis.from_url(
        config.redis_url, socket_timeout=3, socket_connect_timeout=3
    )
    rates = RateGate(redis)
    origins = {
        "registry": config.registry_url,
        "deployments": config.deployments_url,
        "incidents": config.incidents_url,
    }

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if http is None:
                await upstream.aclose()
            if redis_client is None:
                redis.close()

    app = FastAPI(
        title="AegisSRE API Gateway",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def authorized(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)] = None,
    ) -> None:
        if not credentials or not hmac.compare_digest(
            credentials.credentials.encode(), config.api_token.encode()
        ):
            raise HTTPException(
                401, "Valid bearer token required", headers={"WWW-Authenticate": "Bearer"}
            )

    @app.middleware("http")
    async def boundary(request: Request, call_next: Any) -> Response:
        supplied_id = request.headers.get("x-request-id", "")
        correlation = supplied_id if REQUEST_ID.fullmatch(supplied_id) else uuid.uuid4().hex
        request.state.correlation = correlation
        if request.url.path.startswith("/api/"):
            scheme, _, token = request.headers.get("authorization", "").partition(" ")
            valid = (
                scheme.lower() == "bearer"
                and len(token) <= 512
                and hmac.compare_digest(token.encode(), config.api_token.encode())
            )
            principal = (
                "operator:" + hashlib.sha256(config.api_token.encode()).hexdigest()
                if valid
                else "failed:" + (request.client.host if request.client else "unknown")
            )
            try:
                allowed, retry = await asyncio.to_thread(
                    rates.consume,
                    principal,
                    config.requests_per_minute if valid else config.failed_auth_per_minute,
                )
            except RedisError:
                return JSONResponse(
                    {"detail": "Rate-limit dependency unavailable"},
                    status_code=503,
                    headers={"X-Request-ID": correlation},
                )
            if not allowed:
                return JSONResponse(
                    {"detail": "Request rate exceeded"},
                    status_code=429,
                    headers={"Retry-After": str(retry), "X-Request-ID": correlation},
                )
            if not valid:
                return JSONResponse(
                    {"detail": "Valid bearer token required"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer", "X-Request-ID": correlation},
                )
            if request.method not in {"HEAD", "OPTIONS"}:
                chunks: list[bytes] = []
                size = 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 65536:
                        return JSONResponse(
                            {"detail": "Request exceeds 64KB"},
                            status_code=413,
                            headers={"X-Request-ID": correlation},
                        )
                    chunks.append(chunk)
                request._body = b"".join(chunks)
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = correlation
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "healthy", "service": "api-gateway"}

    @app.get(
        PREFIX + "/ready",
        dependencies=[Depends(authorized)],
        responses={503: {"description": "A dependency is unavailable"}},
    )
    async def ready() -> dict[str, str]:
        try:
            if not await asyncio.to_thread(redis.ping):
                raise HTTPException(503, "Redis is unavailable")

            async def probe(name: str, origin: str) -> None:
                headers = (
                    {"Authorization": f"Bearer {config.incidents_token}"}
                    if name == "incidents"
                    else {"Authorization": f"Bearer {config.metadata_token}"}
                )
                async with upstream.stream(
                    "GET", origin.rstrip("/") + "/ready", headers=headers, follow_redirects=False
                ) as response:
                    if response.status_code != 200:
                        raise HTTPException(503, "An upstream is not ready")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 4096:
                            raise HTTPException(503, "Invalid upstream readiness response")
                    try:
                        body = json.loads(raw)
                        if not isinstance(body, dict) or body.get("status") != "ready":
                            raise ValueError("Not ready")
                    except (ValueError, UnicodeError, RecursionError) as exc:
                        raise HTTPException(503, "Invalid upstream readiness response") from exc

            async with asyncio.timeout(8):
                results = await asyncio.gather(
                    *(probe(name, origin) for name, origin in origins.items()),
                    return_exceptions=True,
                )
                if any(isinstance(result, BaseException) for result in results):
                    raise HTTPException(503, "An upstream is not ready")
        except (RedisError, httpx.HTTPError, TimeoutError) as exc:
            raise HTTPException(503, "A gateway dependency is unavailable") from exc
        return {"status": "ready"}

    def make_proxy(route: Route) -> Callable[[Request], Any]:
        async def proxy(request: Request) -> Response:
            for key, value in request.path_params.items():
                if not IDENTIFIER.fullmatch(str(value)) or (
                    key == "decision" and value not in {"approve", "reject", "defer"}
                ):
                    raise HTTPException(404, "Unknown route or identifier")
            params = list(request.query_params.multi_items())
            if len(params) > 20 or any(
                key not in route.queries or len(value) > 1024 for key, value in params
            ):
                raise HTTPException(422, "Unsupported or oversized query parameter")
            raw = await request.body()
            if raw:
                if request.method == "GET":
                    raise HTTPException(400, "GET request bodies are not accepted")
                if (
                    request.headers.get("content-type", "").split(";")[0].lower()
                    != "application/json"
                ):
                    raise HTTPException(415, "Only JSON request bodies are accepted")
                try:
                    body = json.loads(raw)
                    if not isinstance(body, dict):
                        raise ValueError("Expected a JSON object")
                except (ValueError, UnicodeError, RecursionError) as exc:
                    raise HTTPException(422, "A valid JSON object is required") from exc
                if route.asserted_actor:
                    body["actor"] = config.operator
                raw = json.dumps(body).encode()
            headers = {
                "X-Request-ID": request.state.correlation,
                "Content-Type": "application/json",
            }
            if route.upstream == "incidents":
                headers["Authorization"] = f"Bearer {config.incidents_token}"
            else:
                headers["Authorization"] = f"Bearer {config.metadata_token}"
            path = route.path.format(**request.path_params)
            try:
                async with (
                    asyncio.timeout(route.timeout_seconds),
                    upstream.stream(
                        request.method,
                        origins[route.upstream].rstrip("/") + path,
                        params=tuple(params),
                        content=raw,
                        headers=headers,
                        follow_redirects=False,
                        timeout=httpx.Timeout(route.timeout_seconds, connect=3),
                    ) as response,
                ):
                    if 300 <= response.status_code < 400 or response.status_code >= 500:
                        raise HTTPException(502, "Upstream unavailable or returned a redirect")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 8 * 1024 * 1024:
                            raise HTTPException(502, "Upstream response exceeds size limit")
                        chunks.append(chunk)
                    media_type = (
                        "application/json"
                        if "json" in response.headers.get("content-type", "")
                        else "text/plain"
                    )
                    return Response(
                        b"".join(chunks), status_code=response.status_code, media_type=media_type
                    )
            except (httpx.HTTPError, TimeoutError) as exc:
                raise HTTPException(502, "Upstream request failed") from exc

        return proxy

    for route in ROUTES:
        path_parameters = [
            {
                "name": name,
                "in": "path",
                "required": True,
                "schema": {"type": "string", "pattern": IDENTIFIER.pattern},
            }
            for name in re.findall(r"{([^}]+)}", route.path)
        ]
        for method in route.methods:
            extra: dict[str, Any] = {
                "parameters": path_parameters
                + [
                    {
                        "name": key,
                        "in": "query",
                        "required": False,
                        "schema": {
                            "type": "integer"
                            if key == "limit"
                            else "boolean"
                            if key == "include_heartbeats"
                            else "string"
                        },
                    }
                    for key in route.queries
                ]
            }
            if method in {"POST", "PUT"}:
                extra["requestBody"] = {
                    "content": {"application/json": {"schema": {"type": "object"}}}
                }
            app.add_api_route(
                PREFIX + route.path,
                make_proxy(route),
                methods=[method],
                status_code=204 if method == "DELETE" else 200,
                dependencies=[Depends(authorized)],
                name=f"{method}_{route.upstream}_{route.path}",
                openapi_extra=extra,
                responses={
                    **(
                        {201: {"description": "Created"}}
                        if method == "POST" and route.path in {"/services", "/deployments"}
                        else {}
                    ),
                    400: {"description": "Invalid request"},
                    404: {"description": "Unknown resource or route"},
                    413: {"description": "Request too large"},
                    415: {"description": "JSON required"},
                    422: {"description": "Validation failed"},
                    401: {"description": "Authentication required"},
                    429: {"description": "Rate limit exceeded"},
                    502: {"description": "Upstream failure"},
                    503: {"description": "Required dependency unavailable"},
                },
            )
    return app
