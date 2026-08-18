"""Live web-search adapter for the long-term investment AI assistant.

The assistant uses web search for the *latest* information the local
knowledge base cannot hold: new announcements, news, regulatory changes and
industry events.  It is deliberately read-only and bounded.

Two modes are supported:

* ``demo`` — a curated, clearly-labeled research-demonstration index loaded
  from ``artifacts/competition_demo/web_search_index.json``.  It returns
  real-shaped results (title, source, published date, URL) but is explicitly
  marked ``research_demonstration`` so it is never mistaken for live news.
  This is the default for the competition demo, which may run offline.
* ``http`` — an optional pluggable provider (e.g. an OpenAI-compatible
  answers/search endpoint) configured via environment variables.  When the
  provider is absent or fails, the adapter degrades to demo mode and labels
  every result accordingly, rather than fabricating live news.

Product rules enforced here:

* Every result carries title, source, published date and URL — search
  snippets are never presented as facts without a source.
* Snippets are returned as ``text`` and flagged ``verified=False`` so the
  evidence merger treats them as explanations, not confirmed facts.
* The adapter never issues trade instructions and never claims to fetch
  real-time prices.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Iterable, Mapping, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, Field


class WebSearchResult(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    source: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=500)
    published_at: str | None = None
    snippet: str = Field(default="")
    verified: bool = False
    kind: str = "news"
    citation_id: str | None = None
    mode: str = "demo"  # demo | http
    retrieved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class WebSearchResponse(BaseModel):
    results: list[WebSearchResult]
    mode: str
    provider: str | None = None
    degraded: bool = False
    note: str | None = None


class WebSearchProvider(Protocol):
    name: str

    def search(self, query: str, *, limit: int) -> list[WebSearchResult]: ...


@dataclass
class DemoWebSearchProvider:
    """Curated, clearly-labeled research-demonstration search index."""

    index_path: Path | None = None
    name: str = "demo"

    def search(self, query: str, *, limit: int) -> list[WebSearchResult]:
        entries = self._load_index()
        ranked = self._rank(entries, query)
        out: list[WebSearchResult] = []
        for entry in ranked[:limit]:
            out.append(WebSearchResult(
                title=str(entry.get("title", ""))[:200],
                source=str(entry.get("source", "研究演示资料"))[:120],
                url=str(entry.get("url", "internal://demo-search"))[:500],
                published_at=self._iso(entry.get("published_at")),
                snippet=str(entry.get("snippet", ""))[:400],
                verified=bool(entry.get("verified", False)),
                kind=str(entry.get("kind", "news")),
                citation_id=str(entry.get("citation_id") or "") or None,
                mode="demo",
            ))
        return out

    def _load_index(self) -> list[dict[str, object]]:
        path = self.index_path or self._default_path()
        if not path.is_file():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = payload.get("results") if isinstance(payload, dict) else payload
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    def _default_path(self) -> Path:
        root = Path(os.getenv("INVESTMENT_RESEARCH_PROJECT_ROOT", Path.cwd())).resolve()
        return root / "artifacts" / "competition_demo" / "web_search_index.json"

    @staticmethod
    def _rank(entries: Iterable[dict[str, object]], query: str) -> list[dict[str, object]]:
        terms = [item for item in query.lower().split() if len(item) >= 2]
        if not terms:
            return list(entries)

        def score(entry: dict[str, object]) -> int:
            haystack = " ".join(str(entry.get(key, "")) for key in ("title", "snippet", "source", "symbol", "tags")).lower()
            return sum(haystack.count(term) for term in terms)

        return sorted(entries, key=score, reverse=True)

    @staticmethod
    def _iso(value: object) -> str | None:
        if isinstance(value, str) and value:
            return value[:10]
        if isinstance(value, datetime):
            return value.date().isoformat()
        return None


@dataclass
class HttpWebSearchProvider:
    """Optional pluggable HTTP search provider.

    A provider is only used when its endpoint is configured and reachable.
    Any failure degrades to demo mode with a clear note — the assistant
    never fabricates live news to fill the gap.
    """

    endpoint: str | None = None
    api_key: str | None = None
    timeout_seconds: float = 12.0
    name: str = "http"

    def search(self, query: str, *, limit: int) -> list[WebSearchResult]:
        if not self.endpoint:
            raise RuntimeError("web_search_endpoint_not_configured")
        from urllib.request import Request, urlopen  # local import keeps the demo path dependency-free
        import json as _json

        payload = {"query": query, "limit": limit}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.endpoint, data=_json.dumps(payload).encode("utf-8"), method="POST", headers=headers)
        with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - operator-configured endpoint
            body = _json.loads(response.read().decode("utf-8"))
        results = body.get("results") if isinstance(body, dict) else body
        out: list[WebSearchResult] = []
        if not isinstance(results, list):
            return out
        for item in results[:limit]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "")).strip()
            if not url or not self._safe_url(url):
                continue
            out.append(WebSearchResult(
                title=str(item.get("title", ""))[:200],
                source=str(item.get("source", item.get("publisher", "联网搜索")))[:120],
                url=url[:500],
                published_at=self._iso(item.get("published_at") or item.get("date")),
                snippet=str(item.get("snippet", item.get("content", "")))[:400],
                verified=False,
                kind="news",
                citation_id=str(item.get("citation_id") or "") or None,
                mode="http",
            ))
        return out

    @staticmethod
    def _safe_url(url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        host = (parsed.hostname or "").lower()
        return bool(host) and host not in {"localhost", "127.0.0.1", "::1"}

    @staticmethod
    def _iso(value: object) -> str | None:
        if isinstance(value, str) and value:
            return value[:10]
        if isinstance(value, datetime):
            return value.date().isoformat()
        return None


class WebSearchService:
    """Facade selecting the configured provider and degrading safely."""

    def __init__(self, *, demo_index: Path | None = None) -> None:
        self.demo = DemoWebSearchProvider(index_path=demo_index)
        self.http = self._build_http_provider()

    def search(self, query: str, *, limit: int = 6) -> WebSearchResponse:
        if not query or not query.strip():
            return WebSearchResponse(results=[], mode="demo", provider=self.demo.name, note="empty_query")
        bounded = max(1, min(limit, 12))
        provider = self._select_provider()
        try:
            results = provider.search(query.strip(), limit=bounded)
            mode = "http" if isinstance(provider, HttpWebSearchProvider) else "demo"
            degraded = mode == "demo" and self.http is not None and self.http.endpoint
            return WebSearchResponse(
                results=results,
                mode=mode,
                provider=provider.name,
                degraded=degraded,
                note="research_demonstration_index" if mode == "demo" else None,
            )
        except Exception:
            results = self.demo.search(query.strip(), limit=bounded)
            return WebSearchResponse(
                results=results, mode="demo", provider=self.demo.name,
                degraded=True, note="web_search_degraded_to_demo",
            )

    def _select_provider(self) -> WebSearchProvider:
        if self.http is not None and self.http.endpoint:
            return self.http
        return self.demo

    @staticmethod
    def _build_http_provider() -> HttpWebSearchProvider | None:
        endpoint = os.getenv("INVESTMENT_RESEARCH_WEB_SEARCH_ENDPOINT")
        if not endpoint:
            return None
        return HttpWebSearchProvider(
            endpoint=endpoint,
            api_key=os.getenv("INVESTMENT_RESEARCH_WEB_SEARCH_API_KEY"),
            timeout_seconds=float(os.getenv("INVESTMENT_RESEARCH_WEB_SEARCH_TIMEOUT", "12")),
        )


def build_web_search_service() -> WebSearchService:
    return WebSearchService()
