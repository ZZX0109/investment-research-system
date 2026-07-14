from __future__ import annotations

import asyncio

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from investment_research.api.security_middleware import BasicRateLimiter
from investment_research.api.security_middleware import request_size_limit_for_path


def test_request_size_limit_rejects_invalid_content_length() -> None:
    response = asyncio.run(
        BasicRateLimiter().__call__(
            _request(headers={"content-length": "not-a-number"}),
            _ok_response,
        )
    )

    assert response.status_code == 400


def test_request_size_limit_rejects_negative_content_length() -> None:
    response = asyncio.run(
        BasicRateLimiter().__call__(
            _request(headers={"content-length": "-1"}),
            _ok_response,
        )
    )

    assert response.status_code == 400


def test_request_size_limit_rejects_oversized_content_length(monkeypatch) -> None:
    monkeypatch.setenv("API_REQUEST_SIZE_LIMIT_BYTES", "4")

    response = asyncio.run(
        BasicRateLimiter().__call__(
            _request(headers={"content-length": "5"}),
            _ok_response,
        )
    )

    assert response.status_code == 413


def test_document_upload_has_a_separate_bounded_request_limit(monkeypatch) -> None:
    monkeypatch.setenv("API_REQUEST_SIZE_LIMIT_BYTES", "1024")
    monkeypatch.setenv(
        "DOCUMENT_UPLOAD_REQUEST_SIZE_LIMIT_BYTES", str(21 * 1024 * 1024)
    )

    assert request_size_limit_for_path("/api/v1/assets") == 1024
    assert request_size_limit_for_path("/api/v1/documents") == 21 * 1024 * 1024


def test_basic_rate_limiter_returns_429_after_limit(monkeypatch) -> None:
    monkeypatch.delenv("API_RATE_LIMIT_PER_MINUTE", raising=False)
    limiter = BasicRateLimiter(limit=2, window_seconds=60)

    first = asyncio.run(limiter(_request(client_host="198.51.100.10"), _ok_response))
    second = asyncio.run(limiter(_request(client_host="198.51.100.10"), _ok_response))
    third = asyncio.run(limiter(_request(client_host="198.51.100.10"), _ok_response))

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429


def test_basic_rate_limiter_ignores_invalid_env_limit(monkeypatch) -> None:
    monkeypatch.setenv("API_RATE_LIMIT_PER_MINUTE", "not-a-number")
    limiter = BasicRateLimiter(limit=1, window_seconds=60)

    first = asyncio.run(limiter(_request(client_host="203.0.113.20"), _ok_response))
    second = asyncio.run(limiter(_request(client_host="203.0.113.20"), _ok_response))

    assert first.status_code == 200
    assert second.status_code == 429


async def _ok_response(_: Request) -> Response:
    return JSONResponse({"ok": True}, status_code=200)


def _request(
    *,
    headers: dict[str, str] | None = None,
    client_host: str = "127.0.0.1",
) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/test",
            "raw_path": b"/api/v1/test",
            "query_string": b"",
            "headers": [
                (key.lower().encode("latin-1"), value.encode("latin-1"))
                for key, value in (headers or {}).items()
            ],
            "client": (client_host, 49152),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )
