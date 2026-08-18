"""Cross-encoder reranker for knowledge retrieval (Phase 3).

A second-stage reranker re-scores the first-stage fused candidates so a
high-lexical but less-relevant chunk can be pushed below a more relevant one.
The local BGE cross-encoder is an optional dependency; when it is unavailable
the service falls back to a deterministic, dependency-free reranker that
combines keyword overlap, authority and recency — never crashes and always
records which model was used so the retrieval snapshot stays auditable.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from investment_research.domain.knowledge import KnowledgeSearchResult

if TYPE_CHECKING:
    pass


class KnowledgeReranker(Protocol):
    model_name: str
    available: bool

    def rerank(
        self, query: str, candidates: list[KnowledgeSearchResult], *, top_k: int,
        as_of: datetime | None = None,
    ) -> list[KnowledgeSearchResult]:
        """Return candidates re-ordered by relevance, highest first.

        Implementations MUST set ``rerank_score`` on every returned item and
        MUST NOT mutate or drop items silently; every candidate that survives
        the top_k cut is returned with a score.

        ``as_of`` (Phase 7) pins the recency anchor so the same query at the
        same as_of re-ranks identically across wall-clock time — the
        persistent dashboard requires the same question to surface the same
        chunks across turns.  ``None`` falls back to wall-clock time only for
        legacy callers that are not on the as_of-pinned retrieval path.
        """
        ...


class LocalBGEReranker:
    """Optional local ``bge-reranker-base`` cross-encoder (no paid API)."""

    model_name = "bge-reranker-base"
    model_revision = "v1"

    def __init__(self) -> None:
        self._model = None
        self._error: str | None = None
        self.available = False

    def _load(self) -> object | None:
        if self._model is not None or self._error is not None:
            return self._model
        try:  # optional dependency; degrades gracefully
            from FlagEmbedding import FlagReranker  # type: ignore[import-not-found]

            model = FlagReranker("BAAI/bge-reranker-base", use_fp16=True)
            self._model = model
            self.available = True
            return model
        except Exception as exc:  # model/dependency unavailable -> deterministic fallback
            self._error = f"{type(exc).__name__}:{exc}"
            self.available = False
            return None

    def rerank(
        self, query: str, candidates: list[KnowledgeSearchResult], *, top_k: int,
        as_of: datetime | None = None,
    ) -> list[KnowledgeSearchResult]:
        model = self._load()
        if model is None or not candidates:
            return DeterministicReranker().rerank(query, candidates, top_k=top_k, as_of=as_of)
        pairs = [[query, item.snippet or ""] for item in candidates]
        scores = model.compute_score(pairs, normalize=True)  # type: ignore[union-attr]
        if isinstance(scores, float):
            scores = [scores]
        scored = sorted(
            zip(candidates, scores, strict=True),
            key=lambda pair: pair[1], reverse=True,
        )
        chosen = scored[:top_k]
        return [
            item.model_copy(update={"rerank_score": float(score)}) for item, score in chosen
        ]


class DeterministicReranker:
    """Dependency-free reranker: keyword overlap + authority + recency.

    Reproducible so tests and offline evaluation stay stable; the retrieval
    snapshot records ``rerank_model="deterministic-fallback"`` so consumers
    know no neural model was used.
    """

    model_name = "deterministic-fallback"
    available = True

    def rerank(
        self, query: str, candidates: list[KnowledgeSearchResult], *, top_k: int,
        as_of: datetime | None = None,
    ) -> list[KnowledgeSearchResult]:
        terms = {token for token in query.replace("，", " ").split() if token}
        if not terms:
            terms = set(query)
        # Phase 7: anchor recency on as_of (not wall-clock datetime.now) so the
        # same query at the same as_of re-ranks identically across turns on the
        # persistent dashboard.  Fall back to now() only for legacy callers.
        if as_of is not None and candidates:
            anchor = as_of if as_of.utcoffset() is not None else as_of.replace(tzinfo=candidates[0].document.published_at.tzinfo)
        elif candidates:
            anchor = datetime.now(tz=candidates[0].document.published_at.tzinfo)
        else:
            anchor = datetime.now()

        def _score(item: KnowledgeSearchResult) -> float:
            snippet = (item.snippet or "").lower()
            title = item.document.title.lower()
            overlap = sum(1.0 for term in terms if term.lower() in snippet or term.lower() in title)
            overlap_norm = overlap / max(1.0, float(len(terms)))
            authority = item.authority_score
            age_days = max(0.0, (anchor - item.document.published_at).total_seconds() / 86400.0)
            recency = 1.0 / (1.0 + age_days / 180.0)
            # rerank blends overlap (dominant) with the first-stage signal so a
            # clearly relevant chunk still wins when overlap ties.
            return 0.55 * overlap_norm + 0.20 * authority + 0.15 * recency + 0.10 * max(0.0, item.final_score)

        scored = sorted(candidates, key=_score, reverse=True)
        chosen = scored[:top_k]
        return [item.model_copy(update={"rerank_score": _score(item)}) for item in chosen]


def resolve_reranker() -> KnowledgeReranker:
    """Return the best available reranker, falling back deterministically.

    The local cross-encoder is opt-in (``INVESTMENT_RESEARCH_ENABLE_NEURAL_RERANKER=1``)
    because loading it triggers a model download that is slow and network-bound;
    by default the deterministic, dependency-free reranker is used so retrieval
    stays fast and reproducible in tests and offline demos.  The neural model is
    never a hard requirement — when enabled but unavailable it still falls back.
    """
    import os

    if os.environ.get("INVESTMENT_RESEARCH_ENABLE_NEURAL_RERANKER") == "1":
        candidate = LocalBGEReranker()
        candidate._load()  # noqa: SLF001 — probe availability without reranking
        if candidate.available:
            return candidate
    return DeterministicReranker()
