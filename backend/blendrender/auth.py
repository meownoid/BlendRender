from __future__ import annotations

import hashlib
import hmac
import time
from collections import deque

from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

COOKIE_NAME = "blendrender_session"


class SessionManager:
    def __init__(self, password: str, *, secure: bool, max_age: int):
        secret = hashlib.sha256(f"blendrender-session-v1:{password}".encode()).hexdigest()
        self._password = password
        self._serializer = URLSafeTimedSerializer(secret, salt="blendrender-cookie-v1")
        self._secure = secure
        self._max_age = max_age
        self._failures: deque[float] = deque()

    def verify_password(self, candidate: str) -> bool:
        now = time.monotonic()
        while self._failures and now - self._failures[0] > 60:
            self._failures.popleft()
        if len(self._failures) >= 10:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many login attempts. Wait a minute and try again.",
            )
        valid = hmac.compare_digest(candidate.encode(), self._password.encode())
        if not valid:
            self._failures.append(now)
        else:
            self._failures.clear()
        return valid

    def set_cookie(self, response: Response) -> None:
        token = self._serializer.dumps({"authenticated": True})
        response.set_cookie(
            COOKIE_NAME,
            token,
            max_age=self._max_age,
            secure=self._secure,
            httponly=True,
            samesite="strict",
            path="/",
        )

    def clear_cookie(self, response: Response) -> None:
        response.delete_cookie(COOKIE_NAME, path="/", secure=self._secure, samesite="strict")

    def is_authenticated(self, request: Request) -> bool:
        token = request.cookies.get(COOKIE_NAME)
        if not token:
            return False
        try:
            payload: object = self._serializer.loads(token, max_age=self._max_age)
        except (BadSignature, SignatureExpired):
            return False
        return bool(payload == {"authenticated": True})

    def require(self, request: Request) -> None:
        if not self.is_authenticated(request):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )


def reject_cross_origin_mutation(request: Request, *, allow_https_origin: bool = False) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if not origin:
        return
    host = request.headers.get("host", request.url.netloc)
    expected_origins = {f"{request.url.scheme}://{host}"}
    if allow_https_origin:
        # Some TLS-terminating proxies omit X-Forwarded-Proto. Secure cookies ensure that
        # an HTTP origin cannot use an authenticated browser session in this fallback case.
        expected_origins.add(f"https://{host}")
    normalized_origin = origin.rstrip("/")
    if not any(
        hmac.compare_digest(normalized_origin, expected.rstrip("/"))
        for expected in expected_origins
    ):
        raise HTTPException(status_code=403, detail="Cross-origin request rejected")
