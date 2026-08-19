from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from investment_research.api.schemas import (
    AssetCreateRequest,
    EvidenceCreateRequest,
    PositionCreateRequest,
    PriceSeriesCreateRequest,
    ResearchReportCreateRequest,
    WatchlistCreateRequest,
)
from investment_research.domain.base import utc_now
from investment_research.domain.enums import DataMode, DataSourceType
from investment_research.domain.enums import EvidenceType
from investment_research.domain.models import Asset
from investment_research.domain.models import AuditRecord
from investment_research.domain.models import Evidence
from investment_research.domain.models import Position
from investment_research.domain.models import PricePoint
from investment_research.domain.models import PriceSeries
from investment_research.domain.models import ResearchReport
from investment_research.domain.models import User
from investment_research.domain.models import Watchlist
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.data_mode import DataModePolicyService


class PortfolioResearchService:
    """Application service for portfolio, market-data, evidence, and report write/read operations."""

    def __init__(self, uow: SQLiteUnitOfWork) -> None:
        self.uow = uow
        self.mode_policy = DataModePolicyService()

    def list_assets(self, *, source_type: str | None = None) -> list[Asset]:
        try:
            return self.uow.assets.list(source_type=source_type)
        finally:
            self.uow.close()

    def create_asset(self, payload: AssetCreateRequest) -> Asset:
        try:
            asset = self._build_asset(payload)
            return self.uow.assets.add(asset)
        finally:
            self.uow.close()

    def create_asset_for_user(self, payload: AssetCreateRequest, *, user: User) -> Asset:
        try:
            asset = self._build_asset(payload)
            stored = self.uow.assets.add(asset)
            self.uow.domain.assign_owner(
                resource_type="asset", resource_id=stored.id, owner_user_id=user.id
            )
            self._record_audit(
                actor=user.auth_subject,
                action="asset.created",
                target_type="asset",
                target_id=stored.id,
                details={"ticker": stored.ticker, "source_type": stored.provenance.source_type.value},
                data_mode=stored.provenance.data_mode,
            )
            return stored
        finally:
            self.uow.close()

    def remove_asset_for_user(self, asset_id: str, *, user: User) -> None:
        """Remove an asset from one user's workspace while retaining replay evidence."""
        try:
            asset = self.uow.assets.get(asset_id)
            if asset is None:
                raise ValueError("Asset not found")
            self.uow.domain.assert_access(
                resource_type="asset",
                resource_id=asset_id,
                user_id=user.id,
                write=False,
            )
            self._record_audit(
                actor=user.auth_subject,
                action="asset.removed_from_workspace",
                target_type="asset",
                target_id=asset.id,
                details={
                    "ticker": asset.ticker,
                    "retention": "historical_research_evidence_preserved",
                },
                data_mode=asset.provenance.data_mode,
            )
            self.uow.connection.execute(
                "DELETE FROM positions WHERE asset_id=? AND user_id=?",
                (asset_id, str(user.id)),
            )
            self.uow.domain.remove_resource_access(
                resource_type="asset",
                resource_id=asset.id,
                user_id=user.id,
            )
        finally:
            self.uow.close()

    def create_position_for_user(self, payload: PositionCreateRequest, *, user: User) -> Position:
        try:
            asset = self.uow.assets.get(payload.asset_id)
            if asset is None:
                raise ValueError("Asset not found")
            self.uow.domain.assert_access(
                resource_type="asset", resource_id=payload.asset_id, user_id=user.id, write=True
            )
            position = Position(
                user_id=user.id,
                asset_id=UUID(payload.asset_id),
                quantity=payload.quantity,
                cost_basis=payload.cost_basis,
                opened_at=payload.opened_at,
                provenance=self.mode_policy.build_manual_provenance(
                    data_mode=asset.provenance.data_mode,
                    source_name="position-entry",
                    observed_at=payload.opened_at,
                ),
            )
            stored = self.uow.positions.add(position)
            self.uow.domain.assign_owner(
                resource_type="position", resource_id=stored.id, owner_user_id=user.id
            )
            self._record_audit(
                actor=user.auth_subject,
                action="position.created",
                target_type="position",
                target_id=stored.id,
                details={"asset_id": payload.asset_id, "quantity": str(payload.quantity)},
                data_mode=stored.provenance.data_mode,
            )
            return stored
        finally:
            self.uow.close()

    def list_positions_for_user(self, *, user: User) -> list[Position]:
        try:
            return self.uow.positions.list_for_user(str(user.id))
        finally:
            self.uow.close()

    def create_watchlist_for_user(self, payload: WatchlistCreateRequest, *, user: User) -> Watchlist:
        try:
            assets = [self.uow.assets.get(asset_id) for asset_id in payload.asset_ids]
            if any(asset is None for asset in assets):
                raise ValueError("Asset not found")
            asset_modes = [asset.provenance.data_mode for asset in assets if asset is not None]
            watchlist_mode = self.mode_policy.ensure_uniform_mode(data_modes=asset_modes, label="Watchlist assets")
            watchlist = Watchlist(
                user_id=user.id,
                name=payload.name,
                asset_ids=[UUID(asset_id) for asset_id in payload.asset_ids],
                provenance=self.mode_policy.build_manual_provenance(
                    data_mode=watchlist_mode,
                    source_name="watchlist-entry",
                    observed_at=utc_now(),
                ),
            )
            stored = self.uow.watchlists.add(watchlist)
            self.uow.domain.assign_owner(
                resource_type="watchlist", resource_id=stored.id, owner_user_id=user.id
            )
            self._record_audit(
                actor=user.auth_subject,
                action="watchlist.created",
                target_type="watchlist",
                target_id=stored.id,
                details={"name": stored.name, "asset_count": str(len(stored.asset_ids)), "mode": watchlist_mode.value},
                data_mode=watchlist_mode,
            )
            return stored
        finally:
            self.uow.close()

    def list_watchlists_for_user(self, *, user: User) -> list[Watchlist]:
        try:
            return self.uow.watchlists.list_for_user(str(user.id))
        finally:
            self.uow.close()

    def create_price_series(self, payload: PriceSeriesCreateRequest, *, user: User) -> PriceSeries:
        try:
            if self.uow.assets.get(payload.asset_id) is None:
                raise ValueError("Asset not found")
            self.uow.domain.assert_access(
                resource_type="asset", resource_id=payload.asset_id, user_id=user.id, write=True
            )
            series = PriceSeries(
                asset_id=UUID(payload.asset_id),
                interval=payload.interval,
                series_role=payload.series_role,
                reference_symbol=payload.reference_symbol,
                points=[
                    PricePoint(
                        asset_id=UUID(payload.asset_id),
                        timestamp=point.timestamp,
                        open=point.open,
                        high=point.high,
                        low=point.low,
                        close=point.close,
                        volume=point.volume,
                        provenance=self.mode_policy.build_provenance(
                            data_mode=payload.data_mode,
                            source_type=payload.source_type,
                            source_name=payload.source_name,
                            observed_at=point.timestamp,
                            confidence=payload.confidence,
                        ),
                    )
                    for point in payload.points
                ],
                provenance=self.mode_policy.build_provenance(
                    data_mode=payload.data_mode,
                    source_type=payload.source_type,
                    source_name=payload.source_name,
                    observed_at=payload.observed_at,
                    confidence=payload.confidence,
                ),
            )
            stored = self.uow.price_series.add(series)
            self._record_audit(
                actor=user.auth_subject,
                action="price-series.created",
                target_type="price_series",
                target_id=stored.id,
                details={"asset_id": payload.asset_id, "points": str(len(payload.points))},
                data_mode=stored.provenance.data_mode,
            )
            return stored
        finally:
            self.uow.close()

    def list_price_series_for_asset(self, asset_id: str) -> list[PriceSeries]:
        try:
            return self.uow.price_series.list_for_asset(asset_id)
        finally:
            self.uow.close()

    def create_evidence(self, payload: EvidenceCreateRequest, *, user: User) -> Evidence:
        try:
            if self.uow.assets.get(payload.asset_id) is None:
                raise ValueError("Asset not found")
            self.uow.domain.assert_access(
                resource_type="asset", resource_id=payload.asset_id, user_id=user.id, write=True
            )
            evidence = Evidence(
                asset_id=UUID(payload.asset_id),
                evidence_type=EvidenceType(payload.evidence_type),
                title=payload.title,
                summary=payload.summary,
                source_url=payload.source_url,
                collected_at=payload.collected_at,
                published_at=payload.published_at,
                available_at=payload.available_at,
                publication_time_verified=(payload.published_at is not None or payload.available_at is not None),
                payload_ref=payload.payload_ref,
                event_type=payload.event_type,
                direction=payload.direction,
                intensity=payload.intensity,
                source_tier=payload.source_tier,
                surprise_bucket=payload.surprise_bucket,
                guidance_bucket=payload.guidance_bucket,
                filing_type=payload.filing_type,
                raw_hash=payload.raw_hash,
                normalized_hash=payload.normalized_hash,
                data_version=payload.data_version,
                provenance=self.mode_policy.build_provenance(
                    data_mode=payload.data_mode,
                    source_type=payload.source_type,
                    source_name=payload.source_name,
                    observed_at=payload.collected_at,
                    confidence=payload.confidence,
                ),
            )
            stored = self.uow.evidence.add(evidence)
            self.uow.domain.register_evidence(evidence=stored, owner=user)
            self._record_audit(
                actor=user.auth_subject,
                action="evidence.created",
                target_type="evidence",
                target_id=stored.id,
                details={"asset_id": payload.asset_id, "evidence_type": payload.evidence_type},
                data_mode=stored.provenance.data_mode,
            )
            return stored
        finally:
            self.uow.close()

    def list_evidence_for_asset(self, asset_id: str) -> list[Evidence]:
        try:
            return self.uow.evidence.list_for_asset(asset_id)
        finally:
            self.uow.close()

    def create_research_report(self, payload: ResearchReportCreateRequest, *, user: User) -> ResearchReport:
        try:
            if self.uow.assets.get(payload.asset_id) is None:
                raise ValueError("Asset not found")
            if self.uow.analysis_runs.get(payload.analysis_run_id) is None:
                raise ValueError("Analysis run not found")
            report = ResearchReport(
                asset_id=UUID(payload.asset_id),
                analysis_run_id=UUID(payload.analysis_run_id),
                title=payload.title,
                thesis=payload.thesis,
                evidence_ids=[UUID(evidence_id) for evidence_id in payload.evidence_ids],
                report_version=payload.report_version,
                provenance=self.mode_policy.build_provenance(
                    data_mode=payload.data_mode,
                    source_type=payload.source_type,
                    source_name=payload.source_name,
                    observed_at=payload.observed_at,
                    confidence=payload.confidence,
                ),
            )
            stored = self.uow.reports.add(report)
            self.uow.domain.assert_access(
                resource_type="asset", resource_id=payload.asset_id, user_id=user.id, write=True
            )
            self.uow.domain.assign_owner(
                resource_type="research_report", resource_id=stored.id, owner_user_id=user.id
            )
            self._record_audit(
                actor=user.auth_subject,
                action="report.created",
                target_type="research_report",
                target_id=stored.id,
                details={"asset_id": payload.asset_id, "analysis_run_id": payload.analysis_run_id},
                data_mode=stored.provenance.data_mode,
            )
            return stored
        finally:
            self.uow.close()

    def list_reports_for_asset(self, asset_id: str) -> list[ResearchReport]:
        try:
            return self.uow.reports.list_for_asset(asset_id)
        finally:
            self.uow.close()

    def list_audit_records_for_user(self, *, user: User) -> list[AuditRecord]:
        try:
            return self.uow.audit_records.list_for_actor(user.auth_subject)
        finally:
            self.uow.close()

    def list_assets_for_user(self, *, user: User, source_type: str | None = None) -> list[Asset]:
        try:
            permitted = self.uow.domain.accessible_resource_ids(resource_type="asset", user_id=user.id)
            return [asset for asset in self.uow.assets.list(source_type=source_type) if str(asset.id) in permitted]
        finally:
            self.uow.close()

    def list_evidence_for_asset_for_user(self, asset_id: str, *, user: User) -> list[Evidence]:
        try:
            self.uow.domain.assert_access(resource_type="asset", resource_id=asset_id, user_id=user.id)
            return self.uow.evidence.list_for_asset(asset_id)
        finally:
            self.uow.close()

    def list_price_series_for_asset_for_user(self, asset_id: str, *, user: User) -> list[PriceSeries]:
        try:
            self.uow.domain.assert_access(resource_type="asset", resource_id=asset_id, user_id=user.id)
            stored = self.uow.price_series.list_for_asset(asset_id)
            if stored:
                return stored
            asset = self.uow.assets.get(asset_id)
            if asset is not None:
                research_series = self._load_cn_research_price_series(asset)
                if research_series is not None:
                    return [research_series]
            return []
        finally:
            self.uow.close()

    def _load_cn_research_price_series(self, asset: Asset) -> PriceSeries | None:
        """Expose the immutable free-data raw bars for research-mode charting.

        The UI price-series table is intentionally not populated by the free
        PIT rebuild. Without this read-only bridge, a valid research snapshot
        has no chart even though its AKShare raw payload is available. This
        fallback never feeds training or formal inference and only reads the
        append-only research raw layer.
        """
        ticker = asset.ticker.replace(".", "").upper()
        if len(ticker) != 6 or not ticker.isdigit():
            return None
        # The normalized PIT layer is the fast local source for the dashboard.
        # A raw-directory scan over tens of thousands of JSON objects is kept
        # only as a compatibility fallback for older local snapshots.
        parquet_root = (
            Path(__file__).resolve().parents[3]
            / "var"
            / "cn-research"
            / "parquet"
            / "pit"
            / "cn"
            / "standard_daily_bars_research"
            / "free-research-standard-v1"
        )
        parquet_paths = sorted(parquet_root.glob(f"trade_year=*/part-{ticker}-*.parquet"))
        if parquet_paths:
            try:
                import pyarrow.parquet as parquet

                by_date: dict[str, dict[str, object]] = {}
                columns = [
                    "trade_date", "close_native", "open_native", "high_native",
                    "low_native", "volume", "amount", "turnover_rate", "is_suspended",
                ]
                for path in parquet_paths:
                    table = parquet.read_table(path, columns=columns)
                    for row in table.to_pylist():
                        date_value = str(row.get("trade_date") or "")
                        if date_value:
                            by_date.setdefault(date_value, row)
                parquet_rows = [
                    {
                        "日期": date_value,
                        "开盘": row.get("open_native"),
                        "最高": row.get("high_native"),
                        "最低": row.get("low_native"),
                        "收盘": row.get("close_native"),
                        "成交量": row.get("volume"),
                        "成交额": row.get("amount"),
                        "换手率": row.get("turnover_rate"),
                        "交易状态": "0" if row.get("is_suspended") else "1",
                    }
                    for date_value, row in sorted(by_date.items())
                ]
                if parquet_rows:
                    return self._price_series_from_rows(asset, parquet_rows, source_name="CN research PIT parquet")
            except (ImportError, OSError, ValueError):
                # Fall through to the raw compatibility path below.
                pass
        root = Path(__file__).resolve().parents[3] / "var" / "cn-research" / "raw" / "raw-market" / "sha256"
        candidates: list[list[dict[str, object]]] = []
        if not root.is_dir():
            return None
        for path in root.glob("*/*.json"):
            try:
                text = path.read_text(encoding="utf-8")
                if ticker not in text:
                    continue
                payload = json.loads(text)
            except (OSError, ValueError):
                continue
            if isinstance(payload, list) and payload and isinstance(payload[0], dict):
                rows = [row for row in payload if str(row.get("代码", "")).replace(".", "").endswith(ticker)]
                if rows:
                    candidates.append(rows)
        if not candidates:
            return None
        rows = max(candidates, key=len)
        return self._price_series_from_rows(asset, rows, source_name="AKShare Research PIT raw bars")

    def _price_series_from_rows(
        self,
        asset: Asset,
        rows: list[dict[str, object]],
        *,
        source_name: str,
    ) -> PriceSeries | None:
        if not rows:
            return None
        try:
            observed_at = datetime.fromisoformat(str(rows[-1]["日期"])).replace(tzinfo=timezone.utc)
        except (KeyError, TypeError, ValueError):
            observed_at = datetime.now(timezone.utc)
        provenance = self.mode_policy.build_provenance(
            data_mode=DataMode.REAL,
            source_type=DataSourceType.BACKFILLED,
            source_name=source_name,
            observed_at=observed_at,
            confidence=0.9,
        )
        points: list[PricePoint] = []
        for row in rows:
            try:
                date_value = str(row["日期"])
                timestamp = datetime.fromisoformat(date_value).replace(tzinfo=timezone.utc)
                points.append(PricePoint(
                    asset_id=asset.id,
                    timestamp=timestamp,
                    open=float(row["开盘"]),
                    high=float(row["最高"]),
                    low=float(row["最低"]),
                    close=float(row["收盘"]),
                    volume=float(row.get("成交量", 0) or 0),
                    amount=float(row.get("成交额", 0) or 0),
                    turnover_rate=float(row.get("换手率", 0) or 0),
                    is_suspended=str(row.get("交易状态", "1")) == "0",
                    provenance=provenance,
                ))
            except (KeyError, TypeError, ValueError):
                continue
        if not points:
            return None
        points.sort(key=lambda point: point.timestamp)
        return PriceSeries(asset_id=asset.id, interval="1d", series_role="asset", points=points, provenance=provenance)

    def list_reports_for_asset_for_user(self, asset_id: str, *, user: User) -> list[ResearchReport]:
        try:
            self.uow.domain.assert_access(resource_type="asset", resource_id=asset_id, user_id=user.id)
            return self.uow.reports.list_for_asset(asset_id)
        finally:
            self.uow.close()

    def _build_asset(self, payload: AssetCreateRequest) -> Asset:
        return Asset(
            ticker=payload.ticker.upper(),
            name=payload.name,
            asset_type=payload.asset_type,
            currency=payload.currency.upper(),
            exchange=payload.exchange,
            provenance=self.mode_policy.build_provenance(
                data_mode=payload.data_mode,
                source_type=payload.source_type,
                source_name=payload.source_name,
                observed_at=payload.observed_at,
                confidence=payload.confidence,
            ),
        )

    def _record_audit(
        self,
        *,
        actor: str,
        action: str,
        target_type: str,
        target_id,
        details: dict[str, str],
        data_mode: DataMode,
    ) -> None:
        record = AuditRecord(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            details=details,
            provenance=self.mode_policy.build_audit_provenance(data_mode=data_mode, observed_at=utc_now()),
        )
        self.uow.audit_records.add(record)
