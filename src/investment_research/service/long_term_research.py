from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path

from investment_research.service.deep_long_term import (
    DeepLongTermArtifactError,
    _validate_reading,
    load_deep_long_term_registry_summary,
)


def load_long_term_scorecard(*, project_root: Path, symbol: str) -> dict[str, object]:
    """Read one immutable long-term scorecard and fail closed.

    This service is shared by the REST endpoint and the Agent.  It never
    computes a replacement score when the guarded training artifact is
    missing, blocked, malformed, or does not contain the requested symbol.
    """
    root = project_root.resolve()
    requested = symbol.strip().upper()
    report_path = root / "artifacts" / "long_term_training" / "latest.json"
    base: dict[str, object] = {
        "schema_version": "long-term-scorecard-response-v1",
        "data_tier": "research_pit",
        "deployment_ready": False,
        "symbol": requested,
        "status": "unavailable",
        "scorecard": None,
        "blocking_reasons": [],
        "source_ref": str(report_path.relative_to(root)),
        "source_hash": None,
        "long_term_model_readings": None,
        "model_readings_source_ref": None,
        "model_readings_source_hash": None,
        "long_term_model_registry": load_deep_long_term_registry_summary(project_root=root),
    }
    try:
        raw = report_path.read_bytes()
    except OSError:
        base["status"] = "blocked"
        base["blocking_reasons"] = ["long_term_training_report_missing"]
        return base
    base["source_hash"] = sha256(raw).hexdigest()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        base["status"] = "blocked"
        base["blocking_reasons"] = ["long_term_training_report_invalid"]
        return base
    if not isinstance(payload, dict):
        base["status"] = "blocked"
        base["blocking_reasons"] = ["long_term_training_report_invalid"]
        return base
    report_status = str(payload.get("status", "blocked"))
    if report_status != "research_only":
        base["status"] = "blocked"
        reasons = payload.get("blocking_reasons")
        if isinstance(reasons, list):
            base["blocking_reasons"] = [str(reason) for reason in reasons if reason]
        elif reasons:
            base["blocking_reasons"] = [str(reasons)]
        if not base["blocking_reasons"]:
            base["blocking_reasons"] = [f"long_term_training_status:{report_status}"]
        return base
    scorecards = payload.get("scorecards")
    if not isinstance(scorecards, list):
        base["status"] = "blocked"
        base["blocking_reasons"] = ["long_term_scorecards_missing"]
        return base
    candidates = [
        item for item in scorecards
        if isinstance(item, dict) and _symbol_key(str(item.get("symbol", ""))) == _symbol_key(requested)
    ]
    if not candidates:
        base["blocking_reasons"] = ["symbol_scorecard_unavailable"]
        return base
    base["status"] = "available"
    selected = max(candidates, key=lambda item: str(item.get("as_of_date", "")))
    readings = selected.get("long_term_model_readings")
    # The separate model-readings artifact is canonical.  Embedded scorecard
    # fields remain a compatibility fallback for older reports only.
    readings_path = root / "artifacts" / "long_term_model_readings" / "latest.json"
    try:
        readings_raw = readings_path.read_bytes()
        readings_payload = json.loads(readings_raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        readings_payload = None
        readings_raw = None
    if (
        isinstance(readings_payload, dict)
        and readings_payload.get("schema_version") == "long-term-model-readings-v1"
        and readings_payload.get("status") == "research_only"
        and readings_payload.get("deployment_ready") is False
    ):
        records = readings_payload.get("readings")
        matching = [
            item for item in records
            if isinstance(item, dict) and _symbol_key(str(item.get("symbol", ""))) == _symbol_key(requested)
        ] if isinstance(records, list) else []
        if matching:
            latest = max(matching, key=lambda item: str(item.get("data_as_of", item.get("as_of_date", ""))))
            tasks = latest.get("tasks")
            if isinstance(tasks, dict) and set(tasks) == {
                "excess_return_120d",
                "excess_return_240d",
                "future_max_drawdown_120d",
                "future_max_drawdown_240d",
            }:
                try:
                    validated = {
                        task: _validate_reading(task, reading)
                        for task, reading in tasks.items()
                    }
                except (DeepLongTermArtifactError, TypeError, ValueError):
                    validated = None
                if validated is not None:
                    base["long_term_model_readings"] = validated
                    base["model_readings_source_ref"] = str(readings_path.relative_to(root))
                    base["model_readings_source_hash"] = sha256(readings_raw or b"").hexdigest()
    # Legacy scorecards may embed a partial or hand-written readings mapping.
    # Never expose that as model output: the product contract requires all four
    # horizons together.  Older complete fixtures remain accepted here for
    # backwards-compatible replay; newly generated readings use the separate
    # content-addressed artifact above.
    if base["long_term_model_readings"] is None and _complete_embedded_readings(readings):
        base["long_term_model_readings"] = readings
    base["scorecard"] = selected
    return base


def long_term_evidence_balance(scorecard_response: dict[str, object]) -> dict[str, object]:
    """Translate a scorecard into bounded supporting and contrary facts.

    Thresholds are presentation rules, not model outputs.  Every returned
    fact remains bound to the hash of the source scorecard artifact.
    """
    scorecard = scorecard_response.get("scorecard")
    citation = {
        "source_ref": scorecard_response.get("source_ref"),
        "source_hash": scorecard_response.get("source_hash"),
        "citation_id": (
            f"artifact:{str(scorecard_response.get('source_hash'))[:16]}"
            if scorecard_response.get("source_hash") else None
        ),
    }
    model_citation = {
        "source_ref": scorecard_response.get("model_readings_source_ref"),
        "source_hash": scorecard_response.get("model_readings_source_hash"),
        "citation_id": (
            f"artifact:{str(scorecard_response.get('model_readings_source_hash'))[:16]}"
            if scorecard_response.get("model_readings_source_hash") else None
        ),
    }
    if scorecard_response.get("status") != "available" or not isinstance(scorecard, dict):
        return {
            "ok": True,
            "available": False,
            "supporting_facts": [],
            "contrary_facts": [],
            "model_readings": scorecard_response.get("long_term_model_readings"),
            "blocking_reasons": list(scorecard_response.get("blocking_reasons") or []),
            "citation": citation,
            "model_readings_citation": model_citation,
        }

    supporting: list[dict[str, object]] = []
    contrary: list[dict[str, object]] = []
    positive_dimensions = (
        ("long_term_quality", "经营质量"),
        ("growth_stability", "成长稳定性"),
        ("shareholder_return", "股东回报"),
        ("evidence_completeness", "证据完整度"),
    )
    for field, label in positive_dimensions:
        value = _finite_number(scorecard.get(field))
        if value is not None and value >= 70.0:
            supporting.append({"dimension": label, "value": value, **citation})
        elif value is not None and value < 45.0:
            contrary.append({"dimension": label, "value": value, **citation})
    risk = _finite_number(scorecard.get("long_term_risk"))
    if risk is not None and risk >= 55.0:
        contrary.append({"dimension": "长期风险", "value": risk, **citation})
    elif risk is not None and risk <= 30.0:
        supporting.append({"dimension": "长期风险较低读数", "value": risk, **citation})
    valuation = _finite_number(scorecard.get("valuation_position"))
    if valuation is not None and valuation >= 70.0:
        contrary.append({"dimension": "估值位置偏高", "value": valuation, **citation})
    for limitation in scorecard.get("evidence", []) if isinstance(scorecard.get("evidence"), list) else []:
        contrary.append({"dimension": "数据限制", "detail": str(limitation), **citation})
    return {
        "ok": True,
        "available": True,
        "supporting_facts": supporting,
        "contrary_facts": contrary,
        "model_readings": scorecard_response.get("long_term_model_readings"),
        "citation": citation,
        "model_readings_citation": model_citation,
        "note": "These are thresholded scorecard facts, not trade advice or causal claims.",
    }


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def _symbol_key(value: str) -> str:
    normalized = value.strip().upper()
    return normalized.split(".", 1)[0] if len(normalized.split(".", 1)[0]) == 6 else normalized


def _complete_embedded_readings(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    required = {
        "excess_return_120d",
        "excess_return_240d",
        "future_max_drawdown_120d",
        "future_max_drawdown_240d",
    }
    if set(value) != required:
        return False
    expected_horizons = {
        "excess_return_120d": 120,
        "excess_return_240d": 240,
        "future_max_drawdown_120d": 120,
        "future_max_drawdown_240d": 240,
    }
    for task, reading in value.items():
        if not isinstance(reading, dict):
            return False
        values = [reading.get(field) for field in ("q10", "q50", "q90")]
        if any(not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(float(item)) for item in values):
            return False
        if values != sorted(values):
            return False
        required = ("horizon_days", "model", "model_version", "data_as_of", "snapshot_id", "artifact_hash")
        if any(not reading.get(field) for field in required):
            return False
        try:
            horizon_days = int(reading.get("horizon_days", -1))
        except (TypeError, ValueError):
            return False
        if horizon_days != expected_horizons[task]:
            return False
        artifact_hash = str(reading.get("artifact_hash"))
        if len(artifact_hash) != 64 or any(char not in "0123456789abcdef" for char in artifact_hash):
            return False
    return True


def load_long_term_scorecard_demo(*, project_root: Path, symbol: str) -> dict[str, object]:
    """Read the clearly-labeled competition-demo research fixture.

    This is research-demonstration data (``data_tier=research_demo``,
    ``validation_status=research_demonstration_not_validated``) used so the
    competition demo can run end-to-end when the real
    ``artifacts/long_term_training/latest.json`` is still blocked.  It never
    overwrites the active training artifact and every reading still passes
    the same validation as the real loader.
    """
    root = project_root.resolve()
    requested = symbol.strip().upper()
    demo_path = root / "artifacts" / "competition_demo" / "long_term_research_demo.json"
    base: dict[str, object] = {
        "schema_version": "long-term-scorecard-response-v1",
        "data_tier": "research_demo",
        "deployment_ready": False,
        "symbol": requested,
        "status": "unavailable",
        "scorecard": None,
        "blocking_reasons": [],
        "source_ref": str(demo_path.relative_to(root)) if demo_path.is_file() else "artifacts/competition_demo/long_term_research_demo.json",
        "source_hash": None,
        "long_term_model_readings": None,
        "model_readings_source_ref": None,
        "model_readings_source_hash": None,
        "validation_status": "research_demonstration_not_validated",
        "long_term_model_registry": load_deep_long_term_registry_summary(project_root=root),
    }
    try:
        raw = demo_path.read_bytes()
    except OSError:
        base["status"] = "blocked"
        base["blocking_reasons"] = ["competition_demo_fixture_missing"]
        return base
    base["source_hash"] = sha256(raw).hexdigest()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        base["status"] = "blocked"
        base["blocking_reasons"] = ["competition_demo_fixture_invalid"]
        return base
    if not isinstance(payload, dict) or payload.get("data_tier") != "research_demo":
        base["status"] = "blocked"
        base["blocking_reasons"] = ["competition_demo_fixture_invalid"]
        return base
    scorecards = payload.get("scorecards")
    if not isinstance(scorecards, list):
        base["status"] = "blocked"
        base["blocking_reasons"] = ["competition_demo_scorecards_missing"]
        return base
    candidates = [
        item for item in scorecards
        if isinstance(item, dict) and _symbol_key(str(item.get("symbol", ""))) == _symbol_key(requested)
    ]
    if not candidates:
        base["blocking_reasons"] = ["symbol_scorecard_unavailable"]
        return base
    base["status"] = "available"
    selected = max(candidates, key=lambda item: str(item.get("as_of_date", "")))
    readings = selected.get("long_term_model_readings")
    if isinstance(readings, dict):
        validated: dict[str, object] = {}
        for task, reading in readings.items():
            if not isinstance(reading, dict):
                continue
            try:
                validated[task] = _validate_reading(task, reading)
            except (DeepLongTermArtifactError, TypeError, ValueError):
                continue
        if set(validated) == {
            "excess_return_120d", "excess_return_240d",
            "future_max_drawdown_120d", "future_max_drawdown_240d",
        }:
            base["long_term_model_readings"] = validated
            base["model_readings_source_ref"] = str(demo_path.relative_to(root))
            base["model_readings_source_hash"] = sha256(raw).hexdigest()
    base["scorecard"] = selected
    return base
