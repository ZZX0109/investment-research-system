from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_AUDIT_ALLOWLIST = (
    "sec.gov",
    "cninfo.com.cn",
    "hkexnews.hk",
    "sse.com.cn",
    "szse.cn",
    "nasdaq.com",
    "nyse.com",
)


@dataclass(frozen=True)
class AuthorityRetrieval:
    url: str
    domain: str
    fetched_at: datetime
    content_hash: str
    summary: str
    status: str
    error: str | None = None


class BoundedAuthorityRetriever:
    def __init__(
        self,
        *,
        enabled: bool | None = None,
        max_evidence: int = 12,
        max_rounds: int = 2,
        per_domain: int = 3,
    ) -> None:
        self.enabled = (
            enabled
            if enabled is not None
            else os.getenv("WORKBUDDY_AUDIT_NETWORK_ENABLED", "false").lower() == "true"
        )
        self.max_evidence = max_evidence
        self.max_rounds = max_rounds
        self.per_domain = per_domain
        configured = os.getenv(
            "WORKBUDDY_AUDIT_SOURCE_ALLOWLIST", ",".join(DEFAULT_AUDIT_ALLOWLIST)
        )
        self.allowlist = tuple(
            item.strip().lower() for item in configured.split(",") if item.strip()
        )

    def retrieve(self, urls: list[str]) -> tuple[list[AuthorityRetrieval], int]:
        if not self.enabled:
            return [], 0
        accepted: list[tuple[str, str]] = []
        domain_counts: dict[str, int] = {}
        for url in urls:
            parsed = urlparse(url)
            domain = (parsed.hostname or "").lower()
            if parsed.scheme != "https" or not any(
                domain == item or domain.endswith(f".{item}") for item in self.allowlist
            ):
                continue
            if domain_counts.get(domain, 0) >= self.per_domain:
                continue
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            accepted.append((url, domain))
            if len(accepted) >= self.max_evidence:
                break
        output: list[AuthorityRetrieval] = []
        rounds_used = 0
        pending = accepted
        for round_index in range(self.max_rounds):
            if not pending:
                break
            rounds_used = round_index + 1
            retry: list[tuple[str, str]] = []
            for url, domain in pending:
                try:
                    request = Request(
                        url,
                        headers={
                            "User-Agent": "WorkBuddyResearch/1.0",
                            "Range": "bytes=0-65535",
                        },
                    )
                    with urlopen(request, timeout=4) as response:  # noqa: S310 - URL passed strict host allowlist
                        raw = response.read(65_536)
                    text = re.sub(
                        r"\s+",
                        " ",
                        re.sub(r"<[^>]+>", " ", raw.decode("utf-8", errors="ignore")),
                    ).strip()
                    output.append(
                        AuthorityRetrieval(
                            url,
                            domain,
                            datetime.now(timezone.utc),
                            hashlib.sha256(raw).hexdigest(),
                            text[:600],
                            "fetched",
                        )
                    )
                except Exception as exc:
                    if round_index + 1 < self.max_rounds:
                        retry.append((url, domain))
                    else:
                        output.append(
                            AuthorityRetrieval(
                                url,
                                domain,
                                datetime.now(timezone.utc),
                                "",
                                "",
                                "failed",
                                str(exc),
                            )
                        )
            pending = retry
        return output, rounds_used
