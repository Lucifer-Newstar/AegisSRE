"""Service-boundary authentication, independent of user-supplied message text."""

from __future__ import annotations

import hmac

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class ServiceAuth:
    """Separate read-only collection from operator writes. No per-user identity.

    Only GET health/metrics are public. Use network isolation as well as tokens.
    Local unauthenticated access requires explicit dev mode and no configured key.
    """

    @staticmethod
    def validate(token: str, dev_mode: bool, read_token: str = "") -> None:
        if not dev_mode and (not token or not read_token):
            raise ValueError(
                "Configure distinct metadata API/read tokens or explicitly enable metadata dev mode"
            )
        for item in (token, read_token):
            if item and (len(item) > 512 or any(not 33 <= ord(c) <= 126 for c in item)):
                raise ValueError("Invalid metadata token format")
        if token and read_token and hmac.compare_digest(token, read_token):
            raise ValueError("Metadata API/read tokens must be distinct")

    def __init__(
        self,
        app: ASGIApp,
        token: str,
        dev_mode: bool = False,
        read_token: str = "",
        max_body_bytes: int = 65536,
    ):
        self.validate(token, dev_mode, read_token)
        if not 1024 <= max_body_bytes <= 1_600_000:
            raise ValueError("Invalid service request bound")
        self.app, self.token, self.read_token, self.dev_mode = (
            app,
            token.encode(),
            read_token.encode(),
            dev_mode,
        )
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        public = scope["method"] == "GET" and scope["path"] in {"/health", "/metrics"}
        if not public:
            headers = [value for key, value in scope["headers"] if key.lower() == b"authorization"]
            supplied = headers[0] if len(headers) == 1 else b""
            scheme, _, value = supplied.partition(b" ")
            well_formed = len(supplied) <= 520 and scheme.lower() == b"bearer"
            operator = bool(self.token) and hmac.compare_digest(value, self.token)
            reader = bool(self.read_token) and hmac.compare_digest(value, self.read_token)
            valid = well_formed and (operator or (reader and scope["method"] in {"GET", "HEAD"}))
            dev = self.dev_mode and not (self.token or self.read_token)
            if not valid and not dev:
                forbidden = well_formed and reader
                await JSONResponse(
                    {
                        "detail": "Read-only service credential"
                        if forbidden
                        else "Valid service bearer token required"
                    },
                    status_code=403 if forbidden else 401,
                    headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
                )(scope, receive, send)
                return
        if scope["method"] in {"POST", "PUT", "PATCH"}:
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                if message["type"] != "http.request":
                    continue
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > self.max_body_bytes:
                    await JSONResponse(
                        {"detail": "Request exceeds service bound"}, status_code=413
                    )(scope, receive, send)
                    return
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            pending = True

            async def replay() -> Message:
                nonlocal pending
                if pending:
                    pending = False
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await self.app(scope, replay, send)
        else:
            await self.app(scope, receive, send)
