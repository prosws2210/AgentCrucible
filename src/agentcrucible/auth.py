"""Token authentication for the API and dashboard.

Off unless a token is configured:
    CRUCIBLE_API_TOKEN     full access (start runs, run audits)
    CRUCIBLE_VIEWER_TOKEN  read-only (GET requests only); optional

Clients send `Authorization: Bearer <token>`, or log in once through POST /api/auth/login, which sets an
HttpOnly session cookie (so the dashboard and links to HTML reports work in a browser). The cookie holds an
HMAC of the role keyed by the token, never the token itself.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import JSONResponse

COOKIE = "crucible_session"
OPEN_PATHS = ("/api/health", "/api/auth/")


@dataclass
class Tokens:
    admin: str | None
    viewer: str | None

    @classmethod
    def from_env(cls) -> "Tokens":
        return cls(os.environ.get("CRUCIBLE_API_TOKEN") or None, os.environ.get("CRUCIBLE_VIEWER_TOKEN") or None)

    @property
    def required(self) -> bool:
        return bool(self.admin or self.viewer)

    def role_for_token(self, token: str | None) -> str | None:
        if not token:
            return None
        if self.admin and hmac.compare_digest(token, self.admin):
            return "admin"
        if self.viewer and hmac.compare_digest(token, self.viewer):
            return "viewer"
        return None

    def session_for(self, role: str) -> str:
        key = self.admin if role == "admin" else self.viewer
        assert key
        return f"{role}.{hmac.new(key.encode(), role.encode(), hashlib.sha256).hexdigest()}"

    def role_for_session(self, value: str | None) -> str | None:
        if not value or "." not in value:
            return None
        role = value.split(".", 1)[0]
        if role not in ("admin", "viewer") or not (self.admin if role == "admin" else self.viewer):
            return None
        return role if hmac.compare_digest(value, self.session_for(role)) else None

    def role_for_request(self, request: Request) -> str | None:
        if not self.required:
            return "admin"
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return self.role_for_token(auth[7:].strip())
        return self.role_for_session(request.cookies.get(COOKIE))


def middleware(tokens: Tokens):
    async def check(request: Request, call_next):
        path = request.url.path
        if not tokens.required or not path.startswith("/api/") or path.startswith(OPEN_PATHS) or request.method == "OPTIONS":
            return await call_next(request)
        role = tokens.role_for_request(request)
        if role is None:
            return JSONResponse({"detail": "authentication required"}, 401)
        if role == "viewer" and request.method not in ("GET", "HEAD"):
            return JSONResponse({"detail": "this token is read-only"}, 403)
        request.state.role = role
        return await call_next(request)

    return check
