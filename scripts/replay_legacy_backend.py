#!/usr/bin/env python3
"""Idempotently replay archived backend facts into the relational domain.

The archive is only read. A current user owns the imported records, while every
legacy row receives a stable mapping and a payload hash for later verification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from investment_research.domain.base import Provenance, utc_now
from investment_research.domain.enums import AssetType, DataMode, DataSourceType, EvidenceType
from investment_research.domain.long_term_models import Claim
from investment_research.domain.models import AnalysisRun, Asset, Evidence, ResearchReport
from investment_research.repository.sqlite import SQLiteUnitOfWork, create_unit_of_work


ROOT = Path(__file__).resolve().parents[1]
LEGACY_DEFAULT = ROOT / "investment-research-system" / "data" / "investment_research.sqlite3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay archived backend data into the current domain store.")
    parser.add_argument("--legacy-db", type=Path, default=LEGACY_DEFAULT)
    parser.add_argument("--owner-email", required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def provenance(observed_at: datetime) -> Provenance:
    return Provenance(
        data_mode=DataMode.SANDBOX,
        source_type=DataSourceType.BACKFILLED,
        source_name="legacy-replay",
        observed_at=observed_at,
        confidence=0.5,
    )


def timestamp(value: str | None) -> datetime:
    if not value:
        return utc_now()
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def stable_id(kind: str, value: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"investment-research-legacy:{kind}:{value}")


def row_hash(row: sqlite3.Row) -> str:
    payload = json.dumps(dict(row), sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


class Replay:
    def __init__(self, *, source: sqlite3.Connection, target: SQLiteUnitOfWork, owner) -> None:
        self.source = source
        self.target = target
        self.owner = owner
        self.counts = {"assets": 0, "evidence": 0, "claims": 0, "runs": 0, "reports": 0, "skipped": 0, "failures": 0}
        self.assets: dict[str, UUID] = {}
        self.evidence: dict[str, UUID] = {}
        self.runs: dict[str, UUID] = {}

    def run(self) -> dict[str, int]:
        self._holdings()
        self._evidence()
        self._runs()
        self._reports()
        self.target.connection.commit()
        return self.counts

    def _holdings(self) -> None:
        if not table_exists(self.source, "holdings"):
            return
        for row in self.source.execute("SELECT * FROM holdings ORDER BY symbol"):
            key = str(row["symbol"])
            asset_id = self._mapped("holdings", key)
            if asset_id:
                self.assets[key] = UUID(asset_id)
                self.counts["skipped"] += 1
                continue
            asset = Asset(
                id=stable_id("asset", key), ticker=key, name=str(row["name"]),
                asset_type=AssetType.ETF if "ETF" in str(row["name"]).upper() else AssetType.EQUITY,
                exchange=None, provenance=provenance(utc_now()),
            )
            self.target.assets.add(asset)
            self.target.domain.assign_owner(resource_type="asset", resource_id=asset.id, owner_user_id=self.owner.id)
            self.assets[key] = asset.id
            self._map("holdings", key, "asset", asset.id, row)
            self.counts["assets"] += 1

    def _evidence(self) -> None:
        if not table_exists(self.source, "evidence_records"):
            return
        for row in self.source.execute("SELECT * FROM evidence_records ORDER BY id"):
            legacy_id = str(row["id"])
            if self._mapped("evidence_records", legacy_id):
                self.counts["skipped"] += 1
                continue
            asset_id = self.assets.get(str(row["symbol"]))
            if asset_id is None:
                self._failure("evidence_records", legacy_id, "No migrated asset for symbol")
                continue
            observed_at = timestamp(row["observed_at"])
            source_type = str(row["source_type"])
            evidence_type = EvidenceType.NEWS if source_type == "news_event" else EvidenceType.RESEARCH_NOTE
            evidence = Evidence(
                id=stable_id("evidence", legacy_id), asset_id=asset_id, evidence_type=evidence_type,
                title=str(row["claim"])[:180], summary=str(row["claim"]), source_url=row["source_url"],
                collected_at=observed_at, published_at=observed_at, payload_ref=f"legacy://evidence_records/{legacy_id}",
                normalized_hash=row_hash(row), provenance=provenance(observed_at),
            )
            self.target.evidence.add(evidence)
            self.target.domain.register_evidence(evidence=evidence, owner=self.owner)
            self.evidence[legacy_id] = evidence.id
            self._map("evidence_records", legacy_id, "evidence", evidence.id, row)
            claim = Claim(
                id=stable_id("claim", legacy_id), asset_id=asset_id, owner_user_id=self.owner.id,
                statement=str(row["claim"]), direction="unknown", confidence=float(row["confidence"]),
                evidence_ids=[evidence.id],
            )
            self.target.domain.submit_claim(claim, owner=self.owner)
            self._map("evidence_records", f"claim:{legacy_id}", "claim", claim.id, row)
            self.counts["evidence"] += 1
            self.counts["claims"] += 1

    def _runs(self) -> None:
        if not table_exists(self.source, "research_runs"):
            return
        for row in self.source.execute("SELECT * FROM research_runs ORDER BY started_at"):
            legacy_id = str(row["run_id"])
            if self._mapped("research_runs", legacy_id):
                self.counts["skipped"] += 1
                continue
            asset_id = self.assets.get(str(row["symbol"]))
            if asset_id is None:
                self._failure("research_runs", legacy_id, "No migrated asset for symbol")
                continue
            run_id = stable_id("run", legacy_id)
            evidence_ids = [self.evidence[str(item)] for item in json.loads(row["evidence_ids_json"] or "[]") if str(item) in self.evidence]
            run = AnalysisRun(
                id=run_id, asset_id=asset_id, triggered_by=self.owner.auth_subject,
                input_snapshot_ref=f"legacy://research_runs/{legacy_id}",
                input_snapshot_hash=row["input_snapshot_hash"] or row_hash(row),
                model_version=row["model_version"], reasoning_steps=json.loads(row["reasoning_steps_json"] or "[]"),
                data_mode="sandbox", provider="legacy-replay", as_of=timestamp(row["finished_at"]),
                evidence_ids=evidence_ids, provenance=provenance(timestamp(row["started_at"])),
            )
            self.target.analysis_runs.add(run)
            self.target.domain.record_research_run(run=run, owner=self.owner, correlation_id=str(run.id))
            self.runs[legacy_id] = run_id
            self._map("research_runs", legacy_id, "analysis_run", run_id, row)
            self.counts["runs"] += 1

    def _reports(self) -> None:
        if not table_exists(self.source, "report_snapshots"):
            return
        for row in self.source.execute("SELECT * FROM report_snapshots ORDER BY created_at"):
            legacy_run_id = str(row["run_id"])
            target_run_id = self.runs.get(legacy_run_id)
            legacy_id = f"report:{legacy_run_id}"
            if self._mapped("report_snapshots", legacy_id):
                self.counts["skipped"] += 1
                continue
            if target_run_id is None:
                self._failure("report_snapshots", legacy_id, "No migrated run")
                continue
            asset_id = self.target.analysis_runs.get(str(target_run_id)).asset_id
            report = ResearchReport(
                id=stable_id("report", legacy_run_id), asset_id=asset_id, analysis_run_id=target_run_id,
                title=f"Legacy report {row['symbol']}", thesis=str(row["markdown"])[:1000],
                report_version=str(row["report_version"]), body_markdown=str(row["markdown"]),
                provenance=provenance(timestamp(row["created_at"])),
            )
            self.target.reports.add(report)
            self.target.domain.assign_owner(resource_type="research_report", resource_id=report.id, owner_user_id=self.owner.id)
            self._map("report_snapshots", legacy_id, "research_report", report.id, row)
            self.counts["reports"] += 1

    def _mapped(self, table: str, legacy_id: str) -> str | None:
        row = self.target.connection.execute(
            "SELECT target_id FROM legacy_replay_mappings WHERE legacy_source=? AND legacy_table=? AND legacy_id=?",
            ("legacy-backend", table, legacy_id),
        ).fetchone()
        return None if row is None else str(row[0])

    def _map(self, table: str, legacy_id: str, target_type: str, target_id: UUID, row: sqlite3.Row) -> None:
        self.target.connection.execute(
            "INSERT INTO legacy_replay_mappings (id,legacy_source,legacy_table,legacy_id,target_type,target_id,payload_hash,migrated_at) VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid4()), "legacy-backend", table, legacy_id, target_type, str(target_id), row_hash(row), utc_now().isoformat()),
        )

    def _failure(self, table: str, legacy_id: str, reason: str) -> None:
        self.target.connection.execute(
            "INSERT INTO legacy_replay_failures (id,legacy_source,legacy_table,legacy_id,reason,created_at) VALUES (?,?,?,?,?,?)",
            (str(uuid4()), "legacy-backend", table, legacy_id, reason, utc_now().isoformat()),
        )
        self.counts["failures"] += 1


def main() -> int:
    args = parse_args()
    if not args.legacy_db.exists():
        raise SystemExit(f"Legacy database not found: {args.legacy_db}")
    source = sqlite3.connect(args.legacy_db)
    source.row_factory = sqlite3.Row
    # The target may be SQLite in local development or PostgreSQL in a durable
    # environment. The archived source remains read-only SQLite in both cases.
    target = create_unit_of_work()
    authenticated = target.users.get_by_email(args.owner_email.lower())
    if authenticated is None:
        raise SystemExit("Owner must be registered in the current system before replay")
    if args.dry_run:
        summary = {table: source.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] if table_exists(source, table) else 0 for table in ("holdings", "evidence_records", "research_runs", "report_snapshots")}
        print(json.dumps({"dry_run": True, "source": str(args.legacy_db), "counts": summary}, ensure_ascii=False))
        target.close()
        return 0
    try:
        result = Replay(source=source, target=target, owner=authenticated.user).run()
        print(json.dumps({"dry_run": False, "source": str(args.legacy_db), "result": result}, ensure_ascii=False))
        return 0
    finally:
        source.close()
        target.close()


if __name__ == "__main__":
    raise SystemExit(main())
