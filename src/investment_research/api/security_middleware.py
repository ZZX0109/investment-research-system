from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from investment_research.config import env_csv
from investment_research.config import env_int
from investment_research.public_demo import competition_mode_enabled


def allowed_origins() -> list[str]:
    return env_csv(
        "WORKBENCH_ALLOWED_ORIGINS",
        [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
    )


def request_size_limit_bytes() -> int:
    return env_int("API_REQUEST_SIZE_LIMIT_BYTES", 1024 * 1024)


def request_size_limit_for_path(path: str) -> int:
    if path == "/api/v1/documents":
        return env_int("DOCUMENT_UPLOAD_REQUEST_SIZE_LIMIT_BYTES", 21 * 1024 * 1024)
    return request_size_limit_bytes()


class BasicRateLimiter:
    def __init__(self, *, limit: int = 600, window_seconds: int = 60) -> None:
        # The competition workspace mounts many read-only panels at once and
        # intentionally has no per-user session boundary. Keep an explicit
        # environment override available, but make a direct competition-mode
        # launch safe without relying on a wrapper script to set it.
        default_limit = 5000 if competition_mode_enabled() else limit
        self.limit = env_int("API_RATE_LIMIT_PER_MINUTE", default_limit)
        self.window_seconds = max(1, window_seconds)
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    async def __call__(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        content_length = request.headers.get("content-length")
        parsed_content_length = _parse_content_length(content_length)
        if parsed_content_length is None:
            return JSONResponse(
                {"detail": "Invalid Content-Length header"},
                status_code=400,
            )
        if parsed_content_length > request_size_limit_for_path(request.url.path):
            return JSONResponse(
                {"detail": "Request body too large"},
                status_code=413,
            )

        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        bucket = self._requests[client]
        while bucket and now - bucket[0] > self.window_seconds:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return JSONResponse(
                {"detail": "Rate limit exceeded"},
                status_code=429,
            )
        bucket.append(now)

        return await call_next(request)


async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'",
    )
    return response


def _parse_content_length(value: str | None) -> int | None:
    if value is None:
        return 0
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None
