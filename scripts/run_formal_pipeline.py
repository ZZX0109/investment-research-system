#!/usr/bin/env python3
"""Single formal entry: fetch -> validate/PIT -> train -> audit -> publish.

All artifacts are staged under one immutable training_run_id. Publication is
atomic and is allowed only when the staged manifest passes every gate.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.training.pipeline_config import (
    PipelineMode,
    load_training_pipeline_config,
)
from investment_research.training.publisher import (
    PublicationBlocked,
    attach_approval_evidence,
    atomic_publish,
    validate_publishable_manifest,
)
from investment_research.training.run_identity import (
    TrainingRunIdentity,
    hash_files,
    write_identity,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the authoritative training pipeline")
    parser.add_argument("--config", type=Path, default=PROJECT / "config" / "formal_training.yaml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--publish", action="store_true", help="Atomically publish only after all manifest gates pass")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_training_pipeline_config(args.config)
    if config.mode != PipelineMode.FORMAL:
        raise ValueError("run_formal_pipeline requires mode=formal")
    identity = TrainingRunIdentity.create(
        mode=config.mode.value,
        config_hash=config.canonical_hash(),
        random_seeds=config.random_seeds,
        feature_contract_version=config.feature_contract_version,
        label_policy_version=config.label_policy_version,
    )
    run_root = (PROJECT / config.run_root(identity.training_run_id)).resolve()
    identity_path = run_root / "training_run.json"
    commands = [
        [sys.executable, str(PROJECT / "scripts" / "fetch_real_data.py")],
        [sys.executable, str(PROJECT / "scripts" / "fetch_real_events.py")],
        [sys.executable, str(PROJECT / "scripts" / "run_retraining.py"), "--data-source", "real", "--profile", config.training_profile],
    ]
    plan = {
        "training_run_id": identity.training_run_id,
        "run_root": str(run_root),
        "config_hash": identity.config_hash,
        "commands": commands,
        "publish_requested": args.publish,
    }
    print(json.dumps(plan, indent=2, ensure_ascii=False))
    if args.dry_run:
        return 0
    write_identity(identity_path, identity)
    unauthorized = [market for market in config.markets if not config.providers[market].authorized]
    if unauthorized:
        identity.status = "blocked"
        identity.failure_reason = "provider authorization/SLA not confirmed: " + ", ".join(unauthorized)
        write_identity(identity_path, identity)
        print(identity.failure_reason, file=sys.stderr)
        return 2

    run_root.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(
        {
            "INVESTMENT_RESEARCH_OUTPUT_DIR": str(run_root),
            "INVESTMENT_RESEARCH_TEMP_DIR": str(run_root / "temp"),
            "INVESTMENT_RESEARCH_AUDIT_DIR": str(run_root / "audits"),
            "INVESTMENT_RESEARCH_RUNS_DIR": str(run_root / "research-runs"),
            "INVESTMENT_RESEARCH_FETCH_START_DATE": config.start_date.isoformat(),
            "INVESTMENT_RESEARCH_FETCH_END_DATE": config.end_date.isoformat(),
            "INVESTMENT_RESEARCH_MARKETS": ",".join(config.markets),
            "INVESTMENT_RESEARCH_TRAINING_RUN_ID": identity.training_run_id,
            "INVESTMENT_RESEARCH_TRAINING_CONFIG_HASH": identity.config_hash,
            "INVESTMENT_RESEARCH_CODE_COMMIT": identity.code_commit,
            "INVESTMENT_RESEARCH_RANDOM_SEEDS": ",".join(str(item) for item in identity.random_seeds),
            "INVESTMENT_RESEARCH_EXPECTED_FEATURE_CONTRACT": config.feature_contract_version,
            "INVESTMENT_RESEARCH_LABEL_POLICY_VERSION": config.label_policy_version,
            "INVESTMENT_RESEARCH_ALLOW_SYNTHETIC_SANDBOX": "false",
        }
    )
    try:
        _run(commands[0], env)
        identity.completed_steps.append("real_data_fetch")
        _run(commands[1], env)
        identity.completed_steps.append("event_fetch")
        raw_files = list(run_root.glob("bundle_*.pkl")) + list(run_root.glob("events_*.pkl"))
        identity.raw_data_hash = hash_files(raw_files)
        env["INVESTMENT_RESEARCH_RAW_DATA_HASH"] = identity.raw_data_hash
        write_identity(identity_path, identity)
        _run(commands[2], env)
        identity.completed_steps.extend(["pit_samples", "training", "walk_forward_validation", "approval_evidence"])
        sample_files = list((run_root / "temp").glob("*samples*.pkl"))
        identity.sample_data_hash = hash_files(sample_files) if sample_files else None
        attach_approval_evidence(
            run_root / "models",
            training_run_id=identity.training_run_id,
            evidence_paths=list((run_root / "audits").glob("approval_report*")),
        )
        identity.status = "staged"
        write_identity(identity_path, identity)
        if args.publish:
            validate_publishable_manifest(
                run_root / "models",
                expected_training_run_id=identity.training_run_id,
                expected_config_hash=identity.config_hash,
                expected_feature_contract=config.feature_contract_version,
                expected_decision_context=config.decision_context,
                require_four_market_evidence=True,
            )
            atomic_publish(run_root / "models", (PROJECT / config.deployment_root).resolve())
            identity.completed_steps.append("published")
            identity.status = "published"
            write_identity(identity_path, identity)
    except (subprocess.CalledProcessError, PublicationBlocked, RuntimeError, ValueError) as exc:
        identity.status = "blocked" if isinstance(exc, PublicationBlocked) else "failed"
        identity.failure_reason = f"{type(exc).__name__}: {exc}"
        write_identity(identity_path, identity)
        print(identity.failure_reason, file=sys.stderr)
        return 1
    return 0


def _run(command: list[str], env: dict[str, str]) -> None:
    subprocess.run(command, cwd=PROJECT, env=env, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
