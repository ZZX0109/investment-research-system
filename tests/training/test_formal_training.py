from datetime import date, datetime, timedelta, timezone

import pytest

from investment_research.training.formal_training import FinalHoldoutLedger


def test_final_holdout_ledger_refuses_second_evaluation_for_same_scope_dataset(tmp_path) -> None:
    ledger = FinalHoldoutLedger(tmp_path / "holdout-ledger.json")
    ledger.claim(scope_id="cn:close_confirmed:drawdown_20d", dataset_hash="a" * 64, fold_hash="b" * 64)
    with pytest.raises(RuntimeError, match="already been evaluated"):
        ledger.claim(scope_id="cn:close_confirmed:drawdown_20d", dataset_hash="a" * 64, fold_hash="b" * 64)
    # A new immutable dataset can be evaluated once under the same release scope.
    ledger.claim(scope_id="cn:close_confirmed:drawdown_20d", dataset_hash="c" * 64, fold_hash="d" * 64)
