from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from importlib.util import find_spec
import json
from pathlib import Path

from investment_research.training.models import TrainingSample, WalkForwardFold
from investment_research.training.validation import (
    FinalHoldoutSplit,
    build_final_holdout_split,
    build_walk_forward_folds,
    samples_for_fold,
)


@dataclass(frozen=True)
class FormalScopeRequest:
    training_run_id: str
    market: str
    decision_context: str
    task: str

    @property
    def scope_id(self) -> str:
        return f"{self.market}:{self.decision_context}:{self.task}"


@dataclass
class FormalScopeRunOutcome:
    request: FormalScopeRequest
    result: object | None = None
    blocked_reasons: list[str] = field(default_factory=list)

    @property
    def completed(self) -> bool:
        return self.result is not None and not self.blocked_reasons


RISK_CANDIDATES = (
    "historical-distribution",
    "linear-baseline",
    "logistic-regression",
    "random-forest",
    "lightgbm",
    "xgboost",
    "time-oof-weighted-ensemble",
)
DIRECTION_CANDIDATES = (
    "constant-class",
    "index-direction",
    "momentum",
    "random",
    "logistic-regression",
    "random-forest",
    "lightgbm",
    "xgboost",
    "time-oof-weighted-ensemble",
)
RETURN_CANDIDATES = (
    "historical-distribution",
    "linear-quantile",
    "quantile-random-forest",
    "lightgbm-quantile",
    "xgboost-quantile",
    "time-oof-weighted-ensemble",
)

MAX_LOCAL_FIT_ROWS = 25_000


def balanced_panel_fit_samples(
    samples: list[TrainingSample], *, max_rows: int = MAX_LOCAL_FIT_ROWS
) -> list[TrainingSample]:
    """Bound one local fit while retaining deterministic coverage of every symbol."""
    if len(samples) <= max_rows:
        return list(samples)
    by_symbol: dict[str, list[TrainingSample]] = {}
    for sample in samples:
        by_symbol.setdefault(sample.symbol, []).append(sample)
    quota = max(1, max_rows // max(1, len(by_symbol)))
    selected: list[TrainingSample] = []
    for symbol in sorted(by_symbol):
        rows = sorted(
            by_symbol[symbol],
            key=lambda item: (
                item.as_of_time,
                str(getattr(item, "label_end", None) or ""),
            ),
        )
        take = min(quota, len(rows))
        if take == len(rows):
            selected.extend(rows)
        elif take == 1:
            selected.append(rows[-1])
        else:
            indexes = {
                round(index * (len(rows) - 1) / (take - 1))
                for index in range(take)
            }
            selected.extend(rows[index] for index in sorted(indexes))
    return sorted(selected, key=lambda item: (item.as_of_time, item.symbol))


@dataclass(frozen=True)
class FormalFoldData:
    fold: WalkForwardFold
    train: list[TrainingSample]
    validation: list[TrainingSample]


@dataclass
class FinalHoldoutGuard:
    """Prevents accidental repeated use of the immutable final holdout."""

    _evaluated_scope_ids: set[str] = field(default_factory=set)

    def claim(self, scope_id: str) -> None:
        if scope_id in self._evaluated_scope_ids:
            raise RuntimeError(f"final holdout has already been evaluated for {scope_id}")
        self._evaluated_scope_ids.add(scope_id)


class FinalHoldoutLedger:
    """Persistent single-use lock for final holdout evaluation per immutable dataset."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def claim(self, *, scope_id: str, dataset_hash: str, fold_hash: str) -> None:
        payload = self._load()
        key = f"{scope_id}:{dataset_hash}"
        if key in payload:
            raise RuntimeError(
                "final holdout has already been evaluated for immutable scope dataset"
            )
        payload[key] = {"scope_id": scope_id, "dataset_hash": dataset_hash, "fold_hash": fold_hash}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, sort_keys=True, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def _load(self) -> dict[str, dict[str, str]]:
        if not self.path.is_file():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("final holdout ledger is corrupt")
        return payload


class FormalScopeTrainingPlan:
    """Build global-date PIT folds without ever consuming legacy pickle caches."""

    def __init__(
        self,
        samples: list[TrainingSample],
        *,
        market: str,
        decision_context: str,
        task: str,
        prediction_horizon_sessions: int,
        train_window_sessions: int = 504,
        validation_window_sessions: int = 126,
    ) -> None:
        if not samples:
            raise ValueError("formal scope has no PIT samples")
        if any(sample.market.value != market for sample in samples):
            raise ValueError("formal scope cannot mix markets")
        if any(sample.decision_context != decision_context for sample in samples):
            raise ValueError("formal scope cannot mix decision contexts")
        if any(sample.labels.label_end is None for sample in samples):
            raise ValueError("formal PIT samples require explicit label_end")
        self.samples = samples
        self.market = market
        self.decision_context = decision_context
        self.task = task
        self.prediction_horizon_sessions = prediction_horizon_sessions
        self.train_window_sessions = train_window_sessions
        self.validation_window_sessions = validation_window_sessions

    @property
    def scope_id(self) -> str:
        return f"{self.market}:{self.decision_context}:{self.task}"

    def build(self) -> tuple[FinalHoldoutSplit, list[FormalFoldData], str]:
        holdout = build_final_holdout_split(self.samples, holdout_sessions=252, stress_sessions=126)
        dates = sorted({sample.as_of_date for sample in holdout.development})
        folds = build_walk_forward_folds(
            dates,
            train_window_days=self.train_window_sessions,
            validation_window_days=self.validation_window_sessions,
            prediction_horizon_days=self.prediction_horizon_sessions,
            embargo_days=self.prediction_horizon_sessions,
        )
        materialized = []
        for fold in folds:
            train, validation = samples_for_fold(holdout.development, fold)
            if train and validation:
                materialized.append(FormalFoldData(fold, train, validation))
        fold_hash = sha256(
            json.dumps(
                [
                    {
                        "fold_id": item.fold.fold_id,
                        "train_start": item.fold.train_start.isoformat(),
                        "train_end": item.fold.train_end.isoformat(),
                        "validation_start": item.fold.validation_start.isoformat(),
                        "validation_end": item.fold.validation_end.isoformat(),
                        "purge": item.fold.purge_days,
                        "embargo": item.fold.embargo_days,
                    }
                    for item in materialized
                ],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return holdout, materialized, fold_hash


def candidates_for_task(task: str) -> tuple[str, ...]:
    if task == "drawdown_20d":
        return RISK_CANDIDATES
    if task in {"direction_1d", "direction_5d"}:
        return DIRECTION_CANDIDATES
    if task == "return_20d":
        return RETURN_CANDIDATES
    raise ValueError(f"unsupported formal task: {task}")


def require_candidate_dependencies(task: str) -> None:
    """Fail before training if a declared formal candidate is unavailable.

    Formal comparison sets are contractual. Silently omitting a missing model
    would falsely present an incomplete comparison as a completed approval run.
    """
    requirements = {
        "drawdown_20d": {"lightgbm": "lightgbm", "xgboost": "xgboost"},
        "direction_1d": {"lightgbm": "lightgbm", "xgboost": "xgboost"},
        "direction_5d": {"lightgbm": "lightgbm", "xgboost": "xgboost"},
        "return_20d": {"lightgbm-quantile": "lightgbm", "xgboost-quantile": "xgboost"},
    }
    missing = [
        f"{candidate}:{module}"
        for candidate, module in requirements.get(task, {}).items()
        if find_spec(module) is None
    ]
    if missing:
        raise RuntimeError("formal candidate dependency unavailable: " + ", ".join(missing))


class FormalScopeTrainingCoordinator:
    """Load one exact PIT catalog scope and dispatch its independent task runner.

    The only dataset boundary is ``PITCatalogAdapter.load_scope``.  Keeping
    this coordinator free of filesystem cache arguments prevents legacy
    ``bundle_*.pkl`` and ``all_samples.pkl`` artifacts from re-entering formal
    training through orchestration glue.
    """

    def __init__(self, *, catalog_adapter, holdout_ledger: FinalHoldoutLedger, runners=None) -> None:
        self.catalog_adapter = catalog_adapter
        self.holdout_ledger = holdout_ledger
        self.runners = runners or {}

    def run_scope(self, request: FormalScopeRequest) -> FormalScopeRunOutcome:
        try:
            dataset = self.catalog_adapter.load_scope(
                training_run_id=request.training_run_id,
                market=request.market,
                decision_context=request.decision_context,
                task=request.task,
            )
            samples = dataset.training_samples()
            runner = self._runner_for(request.task)
            if request.task == "drawdown_20d":
                result = runner.run(
                    samples=samples, market=request.market,
                    decision_context=request.decision_context,
                    dataset_hash=dataset.manifest.dataset_hash,
                    holdout_ledger=self.holdout_ledger,
                )
            elif request.task in {"direction_1d", "direction_5d"}:
                result = runner.run(
                    samples=samples, market=request.market,
                    decision_context=request.decision_context,
                    horizon=int(request.task.removeprefix("direction_").removesuffix("d")),
                    dataset_hash=dataset.manifest.dataset_hash,
                    holdout_ledger=self.holdout_ledger,
                )
            elif request.task == "return_20d":
                result = runner.run(
                    samples=samples, market=request.market,
                    decision_context=request.decision_context,
                    dataset_hash=dataset.manifest.dataset_hash,
                    holdout_ledger=self.holdout_ledger,
                )
            else:
                raise ValueError(f"unsupported formal task: {request.task}")
            return FormalScopeRunOutcome(request=request, result=result)
        except Exception as exc:
            return FormalScopeRunOutcome(
                request=request,
                blocked_reasons=[f"formal_scope_training_blocked:{type(exc).__name__}:{exc}"],
            )

    def run_scopes(self, requests: list[FormalScopeRequest]) -> list[FormalScopeRunOutcome]:
        seen: set[tuple[str, str, str, str]] = set()
        outcomes: list[FormalScopeRunOutcome] = []
        for request in requests:
            key = (
                request.training_run_id, request.market,
                request.decision_context, request.task,
            )
            if key in seen:
                raise ValueError(f"duplicate formal training scope: {request.scope_id}")
            seen.add(key)
            outcomes.append(self.run_scope(request))
        return outcomes

    def _runner_for(self, task: str):
        if task in self.runners:
            return self.runners[task]
        # Lazy imports avoid the circular relation: concrete runners use the
        # fold plan constants defined above.
        if task == "drawdown_20d":
            from investment_research.training.formal_risk_runner import FormalRiskTrainingRunner
            return FormalRiskTrainingRunner()
        if task in {"direction_1d", "direction_5d"}:
            from investment_research.training.formal_direction_runner import FormalDirectionTrainingRunner
            return FormalDirectionTrainingRunner()
        if task == "return_20d":
            from investment_research.training.formal_return_runner import FormalReturnTrainingRunner
            return FormalReturnTrainingRunner()
        raise ValueError(f"unsupported formal task: {task}")
