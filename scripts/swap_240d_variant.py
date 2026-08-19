#!/usr/bin/env python3
"""Swap the registered excess_return_240d model to the higher-rank_ic `screen`
variant (holdout rank_ic +0.1015 vs refine-h256 +0.0496), keeping the shared
v4.2 feature/normalizer contract.  Edits the LIVE roster the runtime reads
(`config/long_term_deep_model_roster.json`) — NOT the artifacts manifest copy —
and keeps `artifacts/long_term_model_registry/latest.json` in sync.  Re-run the
readings driver after this so the 240d q10/q50/q90 use the better weights.
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
LIVE_ROSTER = PROJECT / "config" / "long_term_deep_model_roster.json"
ARTIFACT_REG = PROJECT / "artifacts" / "long_term_model_registry" / "latest.json"
SCREEN_DIR = (PROJECT / "artifacts" / "server-run-auto-long-term-deep-20260817" /
              "deep" / "cn" / "close_confirmed" / "cn_equity_core" /
              "excess_return_240d" / "sequence" / "itransformer" / "variants" / "screen")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _patch_model_entry(m: dict) -> bool:
    if m.get("task") != "excess_return_240d" and not (
        m.get("architecture") == "itransformer" and "240d" in str(m.get("model_ref", ""))
    ):
        # artifacts registry entries carry `task`; live roster entries are keyed
        # by task in the parent dict and may omit it on the leaf.
        pass
    model_pt = SCREEN_DIR / "model.pt"
    feature_order = SCREEN_DIR / "feature_order.json"
    normalizer = SCREEN_DIR / "normalizer.json"
    evaluation = SCREEN_DIR / "sequence_evaluation.json"
    for p in (model_pt, feature_order, normalizer, evaluation):
        if not p.is_file():
            print(f"missing screen artifact: {p}", file=sys.stderr)
            return False
    manifest = json.loads((SCREEN_DIR / "sequence_manifest.json").read_text(encoding="utf-8"))
    rel = lambda p: str(p.relative_to(PROJECT))  # noqa: E731
    m["variant"] = "screen"
    m["model_ref"] = rel(model_pt)
    m["model_hash"] = manifest["artifact_hash"]
    m["evaluation_ref"] = rel(evaluation)
    m["report_hash"] = manifest["report_hash"]
    m["feature_order_ref"] = rel(feature_order)
    m["feature_order_hash"] = manifest["feature_order_hash"]
    m["normalizer_ref"] = rel(normalizer)
    m["normalizer_hash"] = manifest["normalizer_hash"]
    m["fold_hash"] = manifest["fold_hash"]
    m["dataset_hash"] = manifest["dataset_hash"]
    m["feature_contract_version"] = manifest["feature_contract_version"]
    m["window_sessions"] = manifest["window_sessions"]
    return True


def main() -> int:
    # 1) live roster (dict models) — the file the runtime actually reads.
    live = json.loads(LIVE_ROSTER.read_text(encoding="utf-8"))
    models = live.get("models", {})
    if not isinstance(models, dict) or "excess_return_240d" not in models:
        print("live roster has no excess_return_240d entry", file=sys.stderr)
        return 2
    if not _patch_model_entry(models["excess_return_240d"]):
        return 2
    LIVE_ROSTER.write_text(json.dumps(live, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"patched live roster: {LIVE_ROSTER.relative_to(PROJECT)}")
    print("  240d ->", models["excess_return_240d"]["variant"],
          models["excess_return_240d"]["model_hash"][:16])

    # 2) artifacts manifest copy (list models) — keep in sync for the record.
    try:
        reg = json.loads(ARTIFACT_REG.read_text(encoding="utf-8"))
        rmodels = reg.get("models", [])
        if isinstance(rmodels, list):
            for m in rmodels:
                if m.get("task") == "excess_return_240d":
                    _patch_model_entry(m)
                    m.setdefault("task", "excess_return_240d")
            ARTIFACT_REG.write_text(json.dumps(reg, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"synced artifacts copy: {ARTIFACT_REG.relative_to(PROJECT)}")
    except Exception as exc:  # noqa: BLE001
        print(f"(artifacts copy sync skipped: {exc})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
