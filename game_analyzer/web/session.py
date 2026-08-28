"""Signed cookie sessions (stdlib only — no itsdangerous dependency)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

SESSION_COOKIE = "ga_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 14


def _encode(payload: dict[str, Any], secret: str) -> str:
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii")
    sig = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _decode(token: str, secret: str) -> dict[str, Any] | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expected = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        raw = base64.urlsafe_b64decode(body.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


class SignedCookieSessionMiddleware:
    """Minimal session middleware compatible with ``request.session`` dict API."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        secret_key: str,
        session_cookie: str = SESSION_COOKIE,
        max_age: int = SESSION_MAX_AGE,
        same_site: str = "lax",
    ) -> None:
        self.app = app
        self.secret_key = secret_key
        self.session_cookie = session_cookie
        self.max_age = max_age
        self.same_site = same_site

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        connection = HTTPConnection(scope)
        token = connection.cookies.get(self.session_cookie, "")
        scope["session"] = _decode(token, self.secret_key) or {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                session = scope.get("session") or {}
                headers = MutableHeaders(scope=message)
                if session:
                    cookie = (
                        f"{self.session_cookie}={_encode(session, self.secret_key)}; "
                        f"Path=/; Max-Age={self.max_age}; HttpOnly; SameSite={self.same_site}"
                    )
                    headers.append("set-cookie", cookie)
                elif token:
                    headers.append(
                        "set-cookie",
                        f"{self.session_cookie}=; Path=/; Max-Age=0; HttpOnly; SameSite={self.same_site}",
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)
