from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from investment_research.domain.forecasts import (
    ResearchModelRoster,
    ResearchRosterEntry,
)


ABSTAIN_RULES = [
    "feature_coverage_below_85pct",
    "cache_expired_or_unavailable",
    "provider_conflict",
    "artifact_hash_mismatch",
    "out_of_distribution_feature_ratio_above_20pct",
    "direction_total_variation_disagreement_above_0.30",
    "risk_probability_disagreement_above_0.25",
    "return_p50_disagreement_above_0.05",
]


def build_research_roster(
    *,
    task_manifest: dict,
    primary_candidate: str,
    fallback_candidate: str,
    challenger_candidates: list[str],
    cohort_version: str,
    dependency_hash: str,
) -> ResearchModelRoster:
    if task_manifest.get("data_tier") != "research_pit" or task_manifest.get("deployment_ready"):
        raise ValueError("research roster rejects deployable or non-research task manifests")
    task = task_manifest["task"]
    artifact_ref = str(Path(task_manifest["evaluation_ref"]).parent / "research_model.joblib")
    common = {
        "task": task, "artifact_ref": artifact_ref,
        "artifact_hashes": dict(task_manifest["artifact_hashes"]),
        "report_hashes": dict(task_manifest["report_hashes"]),
    }
    primary = ResearchRosterEntry(
        role="primary", candidate_name=primary_candidate, component="primary", **common,
    )
    fallback = ResearchRosterEntry(
        role="fallback", candidate_name=fallback_candidate, component="comparator", **common,
    )
    challengers = [
        ResearchRosterEntry(
            role="challenger", candidate_name=name, component="comparator", **common,
        )
        for name in challenger_candidates
    ]
    payload = {
        "market": task_manifest["market"],
        "decision_context": task_manifest["decision_context"],
        "cohort": task_manifest["cohort"],
        "cohort_version": cohort_version,
        "task": task,
        "training_run_id": task_manifest["training_run_id"],
        "dataset_hash": task_manifest["dataset_hash"],
        "market_snapshot_hash": task_manifest["market_snapshot_refs"][0]["market_snapshot_hash"],
        "code_hash": task_manifest["code_hash"],
        "dependency_hash": dependency_hash,
        "primary": primary.model_dump(mode="json"),
        "fallback": fallback.model_dump(mode="json"),
        "challengers": [item.model_dump(mode="json") for item in challengers],
        "limitations": [
            "research_grade_public_data", "not_real_time", "not_investment_advice",
            "historical_available_at_unproven_public_backfill",
        ],
        "abstain_rules": ABSTAIN_RULES,
    }
    roster_hash = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return ResearchModelRoster(**payload, roster_hash=roster_hash)


def load_verified_research_roster(
    path: Path,
    *,
    market: str,
    decision_context: str,
    cohort_version: str,
    task: str,
    project_root: Path,
) -> ResearchModelRoster:
    roster = ResearchModelRoster.model_validate_json(path.read_text(encoding="utf-8"))
    if (roster.market, roster.decision_context, roster.cohort_version, roster.task) != (
        market, decision_context, cohort_version, task,
    ):
        raise ValueError("research roster exact scope mismatch")
    payload = roster.model_dump(mode="json", exclude={"schema_version", "data_tier", "status", "deployment_ready", "roster_hash", "feature_contract_version"})
    expected = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if expected != roster.roster_hash:
        raise ValueError("research roster hash mismatch")
    for entry in (roster.primary, roster.fallback, *roster.challengers):
        for name, digest in entry.artifact_hashes.items():
            artifact = _safe_project_path(project_root, Path(entry.artifact_ref).parent / name)
            if not artifact.is_file() or sha256(artifact.read_bytes()).hexdigest() != digest:
                raise ValueError(f"research artifact hash mismatch:{name}")
        for name, digest in entry.report_hashes.items():
            report = _safe_project_path(project_root, Path(entry.artifact_ref).parent / "reports" / f"{name}.json")
            if not report.is_file():
                raise ValueError(f"research report missing:{name}")
            body = json.loads(report.read_text(encoding="utf-8"))
            recalculated = sha256(
                json.dumps(body.get("payload"), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            if body.get("report_hash") != digest or recalculated != digest:
                raise ValueError(f"research report hash mismatch:{name}")
    return roster


def _safe_project_path(project_root: Path, reference: Path) -> Path:
    if reference.is_absolute():
        raise ValueError("research roster references must be project-relative")
    target = (project_root / reference).resolve()
    if project_root.resolve() not in target.parents:
        raise ValueError("research roster reference escapes project root")
    return target
