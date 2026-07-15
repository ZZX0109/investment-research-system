from types import SimpleNamespace

from investment_research.training.formal_training import (
    FinalHoldoutLedger,
    FormalScopeRequest,
    FormalScopeTrainingCoordinator,
)


class _Dataset:
    manifest = SimpleNamespace(dataset_hash="a" * 64)

    def training_samples(self):
        return ["pit-only-sample"]


class _Catalog:
    def __init__(self):
        self.calls = []

    def load_scope(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["market"] == "hk":
            raise RuntimeError("provider data missing")
        return _Dataset()


class _Runner:
    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return {"task": kwargs.get("horizon", "risk_or_return")}


def test_coordinator_reads_exact_catalog_scope_and_isolates_failures(tmp_path) -> None:
    catalog = _Catalog()
    risk = _Runner()
    direction = _Runner()
    coordinator = FormalScopeTrainingCoordinator(
        catalog_adapter=catalog,
        holdout_ledger=FinalHoldoutLedger(tmp_path / "holdout.json"),
        runners={"drawdown_20d": risk, "direction_5d": direction},
    )
    outcomes = coordinator.run_scopes([
        FormalScopeRequest("run-1", "cn", "close_confirmed", "drawdown_20d"),
        FormalScopeRequest("run-1", "us", "pre_open", "direction_5d"),
        FormalScopeRequest("run-1", "hk", "close_confirmed", "drawdown_20d"),
    ])
    assert [item.completed for item in outcomes] == [True, True, False]
    assert direction.calls[0]["horizon"] == 5
    assert risk.calls[0]["dataset_hash"] == "a" * 64
    assert catalog.calls[1] == {
        "training_run_id": "run-1", "market": "us",
        "decision_context": "pre_open", "task": "direction_5d",
    }
    assert "provider data missing" in outcomes[2].blocked_reasons[0]


def test_coordinator_rejects_duplicate_scope_before_execution(tmp_path) -> None:
    coordinator = FormalScopeTrainingCoordinator(
        catalog_adapter=_Catalog(), holdout_ledger=FinalHoldoutLedger(tmp_path / "holdout.json"),
        runners={"drawdown_20d": _Runner()},
    )
    scope = FormalScopeRequest("run-1", "cn", "close_confirmed", "drawdown_20d")
    try:
        coordinator.run_scopes([scope, scope])
    except ValueError as exc:
        assert "duplicate formal training scope" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("duplicate scope must not be run twice")
