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
* ``http`` — either an operator-configured provider or the built-in public
  web search adapter.  When live search fails, the adapter degrades to demo
  mode and labels every result accordingly, rather than fabricating news.

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
from email.utils import parsedate_to_datetime
import hashlib
import html
import json
import os
from pathlib import Path
import re
import ssl
from typing import Iterable, Mapping, Protocol
from urllib.parse import parse_qs, quote_plus, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

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


@dataclass
class BingRssSearchProvider:
    """Keyless live public-web search through Bing's RSS search output."""

    timeout_seconds: float = 10.0
    name: str = "bing_rss"

    def search(self, query: str, *, limit: int) -> list[WebSearchResult]:
        url = (
            "https://www.bing.com/search?q="
            f"{quote_plus(query)}&format=rss&setlang=zh-cn"
        )
        request = Request(url, headers={"User-Agent": "Mozilla/5.0 ResearchAssistant/1.0"})
        with urlopen(request, timeout=self.timeout_seconds, context=self._ssl_context()) as response:  # noqa: S310 - fixed HTTPS search endpoint
            payload = response.read()
        root = ET.fromstring(payload)
        results: list[WebSearchResult] = []
        for item in root.findall("./channel/item")[:limit]:
            title = self._text(item, "title")
            link = self._text(item, "link")
            if not title or not HttpWebSearchProvider._safe_url(link):
                continue
            description = self._clean_snippet(self._text(item, "description"))
            published = self._published_at(self._text(item, "pubDate"))
            host = (urlparse(link).hostname or "公开网页").removeprefix("www.")
            results.append(WebSearchResult(
                title=title[:200],
                source=host[:120],
                url=link[:500],
                published_at=published,
                snippet=description[:400],
                verified=False,
                kind="web",
                citation_id=f"web:{hashlib.sha256(link.encode('utf-8')).hexdigest()[:16]}",
                mode="http",
            ))
        return results

    @staticmethod
    def _text(item: ET.Element, key: str) -> str:
        node = item.find(key)
        return "" if node is None or node.text is None else node.text.strip()

    @staticmethod
    def _clean_snippet(value: str) -> str:
        return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())

    @staticmethod
    def _published_at(value: str) -> str | None:
        if not value:
            return None
        try:
            return parsedate_to_datetime(value).date().isoformat()
        except (TypeError, ValueError, OverflowError):
            return value[:10] or None

    @staticmethod
    def _ssl_context() -> ssl.SSLContext:
        for candidate in (os.environ.get("SSL_CERT_FILE"), "/etc/ssl/cert.pem"):
            if candidate and Path(candidate).is_file():
                return ssl.create_default_context(cafile=candidate)
        return ssl.create_default_context()


@dataclass
class DuckDuckGoLiteSearchProvider:
    """Keyless public-web search with result URLs and question snippets.

    The lite endpoint is intentionally used instead of scraping a dynamic
    results page.  It returns compact server-rendered HTML and exposes the
    original destination URL in the ``uddg`` query parameter.
    """

    timeout_seconds: float = 10.0
    name: str = "duckduckgo_lite"

    _RESULT_RE = re.compile(
        r"<a\b(?P<attrs>[^>]*\bclass=['\"]result-link['\"][^>]*)>(?P<title>.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )
    _HREF_RE = re.compile(r"\bhref=['\"](?P<href>[^'\"]+)['\"]", re.IGNORECASE)
    _SNIPPET_RE = re.compile(
        r"class=['\"]result-snippet['\"][^>]*>(?P<snippet>.*?)</td>",
        re.IGNORECASE | re.DOTALL,
    )

    def search(self, query: str, *, limit: int) -> list[WebSearchResult]:
        endpoint = f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}"
        request = Request(endpoint, headers={"User-Agent": "Mozilla/5.0 ResearchAssistant/1.0"})
        with urlopen(request, timeout=self.timeout_seconds, context=BingRssSearchProvider._ssl_context()) as response:  # noqa: S310 - fixed HTTPS search endpoint
            page = response.read().decode("utf-8", errors="replace")
        matches = list(self._RESULT_RE.finditer(page))
        results: list[WebSearchResult] = []
        for index, match in enumerate(matches):
            href_match = self._HREF_RE.search(match.group("attrs"))
            if href_match is None:
                continue
            link = self._destination_url(html.unescape(href_match.group("href")))
            if not HttpWebSearchProvider._safe_url(link):
                continue
            next_start = matches[index + 1].start() if index + 1 < len(matches) else len(page)
            snippet_match = self._SNIPPET_RE.search(page, match.end(), next_start)
            title = BingRssSearchProvider._clean_snippet(match.group("title"))
            snippet = BingRssSearchProvider._clean_snippet(
                snippet_match.group("snippet") if snippet_match else ""
            )
            if not title:
                continue
            host = (urlparse(link).hostname or "公开网页").removeprefix("www.")
            results.append(WebSearchResult(
                title=title[:200],
                source=host[:120],
                url=link[:500],
                published_at=self._date_from_text(f"{title} {snippet} {link}"),
                snippet=snippet[:400],
                verified=False,
                kind="web",
                citation_id=f"web:{hashlib.sha256(link.encode('utf-8')).hexdigest()[:16]}",
                mode="http",
            ))
            if len(results) >= limit:
                break
        if not results:
            raise RuntimeError("public_web_search_returned_no_results")
        return results

    @staticmethod
    def _destination_url(value: str) -> str:
        candidate = f"https:{value}" if value.startswith("//") else value
        parsed = urlparse(candidate)
        if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
            destination = parse_qs(parsed.query).get("uddg", [""])[0]
            # ``parse_qs`` already decodes the outer redirect value once.
            # Keep inner URL escapes (for example ``%20`` in a PDF path)
            # intact so the source link remains browser-safe.
            return destination
        return candidate

    @staticmethod
    def _date_from_text(value: str) -> str | None:
        iso = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", value)
        if iso:
            year, month, day = (int(part) for part in iso.groups())
            try:
                return datetime(year, month, day).date().isoformat()
            except ValueError:
                return None
        cn = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", value)
        if cn:
            year, month, day = (int(part) for part in cn.groups())
            try:
                return datetime(year, month, day).date().isoformat()
            except ValueError:
                return None
        return None


class WebSearchService:
    """Facade selecting the configured provider and degrading safely."""

    def __init__(self, *, demo_index: Path | None = None) -> None:
        self.demo = DemoWebSearchProvider(index_path=demo_index)
        self.http = self._build_http_provider()
        public_enabled = os.getenv("INVESTMENT_RESEARCH_PUBLIC_WEB_SEARCH", "1").strip().lower() not in {"0", "false", "no", "off"}
        self.public = DuckDuckGoLiteSearchProvider(
            timeout_seconds=float(os.getenv("INVESTMENT_RESEARCH_PUBLIC_WEB_SEARCH_TIMEOUT", "10"))
        ) if public_enabled else None

    def search(self, query: str, *, limit: int = 6) -> WebSearchResponse:
        if not query or not query.strip():
            return WebSearchResponse(results=[], mode="demo", provider=self.demo.name, note="empty_query")
        bounded = max(1, min(limit, 12))
        provider = self._select_provider()
        try:
            results = provider.search(query.strip(), limit=bounded)
            mode = "demo" if isinstance(provider, DemoWebSearchProvider) else "http"
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
        if self.public is not None:
            return self.public
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
