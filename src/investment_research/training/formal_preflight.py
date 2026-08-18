from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path

from pydantic import BaseModel, Field

from investment_research.training.pipeline_config import TrainingPipelineConfig


REQUIRED_PIT_FIELDS = (
    "exchange_time",
    "source_time",
    "received_at",
    "persisted_at",
    "available_at",
    "revision",
)
FORMAL_MARKETS = ("cn", "us", "hk", "jp")


class PreflightStatus(str, Enum):
    PASSED = "passed"
    BLOCKED = "blocked"


class MarketPreflight(BaseModel):
    market: str
    status: PreflightStatus
    primary_provider: str
    backup_provider: str | None = None
    catalog_ref: str | None = None
    missing_pit_fields: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)


class FormalPreflightReport(BaseModel):
    schema_version: str = "formal-pit-preflight-v2"
    training_run_id: str
    generated_at: datetime
    status: PreflightStatus
    markets: list[MarketPreflight]
    required_markets: list[str] = Field(default_factory=lambda: list(FORMAL_MARKETS))
    configuration_errors: list[str] = Field(default_factory=list)
    legacy_inputs_rejected: list[str] = Field(default_factory=list)
    required_pit_fields: list[str] = Field(default_factory=lambda: list(REQUIRED_PIT_FIELDS))
    report_hash: str = ""

    @property
    def publishable(self) -> bool:
        return self.status == PreflightStatus.PASSED


def run_formal_preflight(
    config: TrainingPipelineConfig,
    *,
    training_run_id: str,
    project_root: Path,
) -> FormalPreflightReport:
    markets: list[MarketPreflight] = []
    configured_markets = set(config.markets)
    configuration_errors = [
        f"unsupported_formal_market:{market}"
        for market in sorted(configured_markets - set(FORMAL_MARKETS))
    ]
    for market in FORMAL_MARKETS:
        if market not in configured_markets or market not in config.providers:
            markets.append(
                MarketPreflight(
                    market=market,
                    status=PreflightStatus.BLOCKED,
                    primary_provider="not-configured",
                    missing_requirements=["formal_market_not_configured"],
                )
            )
            continue
        provider = config.providers[market]
        missing: list[str] = []
        if not provider.authorized:
            missing.append("provider_authorization_unconfirmed")
        if not provider.authorization_ref:
            missing.append("authorization_evidence_missing")
        if not provider.sla_name or provider.sla_name == "pending-contract":
            missing.append("provider_sla_unconfirmed")
        if not provider.backup:
            missing.append("backup_provider_missing")
        if not provider.catalog_ref:
            missing.append("pit_catalog_ref_missing")
        if not provider.exchange_calendar_ref:
            missing.append("exchange_calendar_reference_missing")
        if not provider.supports_historical_pit:
            missing.append("historical_pit_capability_unconfirmed")
        if not provider.supports_revisions:
            missing.append("revision_capability_unconfirmed")
        missing_fields = sorted(set(REQUIRED_PIT_FIELDS) - set(provider.historical_time_fields))
        if missing_fields:
            missing.append("required_pit_time_fields_missing")
        markets.append(
            MarketPreflight(
                market=market,
                status=PreflightStatus.BLOCKED if missing else PreflightStatus.PASSED,
                primary_provider=provider.primary,
                backup_provider=provider.backup,
                catalog_ref=provider.catalog_ref,
                missing_pit_fields=missing_fields,
                missing_requirements=missing,
            )
        )
    legacy = [
        str(path.relative_to(project_root))
        for path in sorted((project_root / "output").glob("bundle_*.pkl"))
    ]
    status = (
        PreflightStatus.PASSED
        if not configuration_errors and all(item.status == PreflightStatus.PASSED for item in markets)
        else PreflightStatus.BLOCKED
    )
    report = FormalPreflightReport(
        training_run_id=training_run_id,
        generated_at=datetime.now(timezone.utc),
        status=status,
        markets=markets,
        configuration_errors=configuration_errors,
        legacy_inputs_rejected=legacy,
    )
    payload = report.model_dump(mode="json", exclude={"report_hash"})
    report.report_hash = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return report


def write_preflight_report(report: FormalPreflightReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path
