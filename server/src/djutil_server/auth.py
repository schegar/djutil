"""Auth: session cookie for the single user, bearer token for the agent."""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings
from .schemas import LoginRequest, MeResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])

_ph = PasswordHasher()
_bearer = HTTPBearer(auto_error=False)

_failures: dict[str, deque[float]] = defaultdict(deque)
_MAX_FAILURES = 5
_WINDOW_S = 60.0


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    dq = _failures[ip]
    while dq and now - dq[0] > _WINDOW_S:
        dq.popleft()
    if not dq:
        _failures.pop(ip, None)
        return False
    return len(dq) >= _MAX_FAILURES


def _record_failure(ip: str) -> None:
    _failures[ip].append(time.monotonic())


def verify_password(settings: Settings, password: str) -> bool:
    if not settings.admin_password_hash:
        return False
    try:
        return _ph.verify(settings.admin_password_hash, password)
    except (VerifyMismatchError, VerificationError):
        return False


def _settings(request: Request) -> Settings:
    from typing import cast

    return cast(Settings, request.app.state.settings)


async def require_user(request: Request) -> bool:
    if request.session.get("user"):
        return True
    raise HTTPException(status_code=401, detail="Not authenticated")


async def require_agent(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> bool:
    settings = _settings(request)
    if not settings.agent_token:
        raise HTTPException(status_code=503, detail="Agent token not configured")
    if credentials is None or not hmac.compare_digest(
        credentials.credentials, settings.agent_token
    ):
        raise HTTPException(status_code=401, detail="Invalid agent token")
    return True


@router.post("/login", response_model=MeResponse)
def login(body: LoginRequest, request: Request, response: Response) -> MeResponse:
    settings = _settings(request)
    ip = request.client.host if request.client else "unknown"
    if _rate_limited(ip):
        raise HTTPException(status_code=429, detail="Too many attempts")
    if not verify_password(settings, body.password):
        _record_failure(ip)
        raise HTTPException(status_code=401, detail="Invalid password")
    request.session["user"] = "admin"
    return MeResponse(authenticated=True)


@router.post("/logout", response_model=MeResponse)
def logout(request: Request) -> MeResponse:
    request.session.clear()
    return MeResponse(authenticated=False)


@router.get("/me", response_model=MeResponse)
def me(request: Request) -> MeResponse:
    return MeResponse(authenticated=bool(request.session.get("user")))
