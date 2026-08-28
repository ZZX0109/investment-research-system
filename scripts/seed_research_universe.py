"""Seed the CN research target universe into the local asset store.

Reads ``config/cn_research_target_167_symbols.json`` and ingests each ticker as
an ``Asset`` owned by the competition workspace, so the workbench stock picker
lists the full research universe (not just the three demo companies).

Names + instrument type are enriched from the local
``artifacts/cn_security_master/security_master.parquet`` security-master
artifact when present; tickers without a local name fall back to the ticker
itself (enrichable later once akshare is network-reachable).  Exchange is
derived from the symbol prefix (XSHG / XSHE).

Idempotent: re-running lists the assets already owned by the competition user
and skips their tickers, so neither rows nor ownership are duplicated.

Run: ``NODE_ENV=development python3 scripts/seed_research_universe.py``
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.auth.service import AuthService  # noqa: E402
from investment_research.domain.base import Provenance, utc_now  # noqa: E402
from investment_research.domain.enums import (  # noqa: E402
    AssetType,
    DataMode,
    DataSourceType,
)
from investment_research.domain.models import Asset  # noqa: E402
from investment_research.repository.sqlite import create_unit_of_work  # noqa: E402

UNIVERSE_PATH = PROJECT / "config" / "cn_research_target_167_symbols.json"
SECURITY_MASTER_PATH = (
    PROJECT / "artifacts" / "cn_security_master" / "security_master.parquet"
)


def _load_target_symbols() -> list[str]:
    payload = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    symbols = payload["cn"] if isinstance(payload, dict) and "cn" in payload else payload
    return [str(s).zfill(6) for s in symbols if str(s).strip()]


def _load_security_master() -> dict[str, dict[str, str | None]]:
    """Return symbol -> {name, instrument_type} from the local artifact."""
    if not SECURITY_MASTER_PATH.exists():
        return {}
    try:
        import pandas as pd  # noqa: E402

        df = pd.read_parquet(SECURITY_MASTER_PATH)
    except Exception as exc:  # pragma: no cover - artifact optional
        print(f"  [warn] security_master unreadable: {exc}", file=sys.stderr)
        return {}
    out: dict[str, dict[str, str | None]] = {}
    for row in df.itertuples(index=False):
        symbol = str(getattr(row, "symbol", "")).zfill(6)
        if not symbol:
            continue
        out[symbol] = {
            "name": getattr(row, "security_name", None),
            "instrument_type": getattr(row, "instrument_type", None),
        }
    return out


def _exchange_for(symbol: str) -> str:
    # Shanghai (XSHG): 6xx main/STAR, 5xx ETF.  Shenzhen (XSHE): 0xx/1xx/3xx.
    if symbol.startswith(("6", "5")):
        return "XSHG"
    return "XSHE"


def _asset_type_for(instrument_type: str | None) -> AssetType:
    value = (instrument_type or "").lower()
    if value in {"etf", "index"}:
        return AssetType.ETF
    if value in {"equity", "stock"}:
        return AssetType.EQUITY
    return AssetType.EQUITY


def main() -> int:
    symbols = _load_target_symbols()
    print(f"target universe: {len(symbols)} symbols")
    master = _load_security_master()
    print(f"security_master names available for {len(master)} symbols")

    # AuthService/PortfolioResearchService close their uow in finally, so use a
    # throwaway uow to resolve the competition user, then seed assets directly
    # through the repositories on a uow we keep open (each repo add commits).
    user_uow = create_unit_of_work()
    try:
        user = AuthService(user_uow).competition_user()
    finally:
        user_uow.close()

    uow = create_unit_of_work()
    try:
        owned_ids = {
            str(rid)
            for rid in uow.domain.accessible_resource_ids(
                resource_type="asset", user_id=user.id
            )
        }
        existing = {
            a.ticker
            for a in uow.assets.list(source_type=None)
            if str(a.id) in owned_ids
        }
        print(f"already owned by competition user: {len(existing)}")

        created = 0
        skipped = 0
        unnamed = 0
        for ticker in symbols:
            if ticker in existing:
                skipped += 1
                continue
            meta = master.get(ticker, {})
            name = meta.get("name") or ticker
            if name == ticker:
                unnamed += 1
            asset = Asset(
                ticker=ticker.upper(),
                name=name,
                asset_type=_asset_type_for(meta.get("instrument_type")),
                currency="CNY",
                exchange=_exchange_for(ticker),
                provenance=Provenance(
                    data_mode=DataMode.REAL,
                    source_type=DataSourceType.BACKFILLED,
                    source_name="cn-research-universe-seed",
                    observed_at=utc_now(),
                    confidence=0.95,
                ),
            )
            stored = uow.assets.add(asset)
            uow.domain.assign_owner(
                resource_type="asset", resource_id=stored.id, owner_user_id=user.id
            )
            created += 1
            existing.add(ticker)
        uow.connection.commit()
        print(
            f"created={created}  skipped(existing)={skipped}  "
            f"unnamed(name=ticker)={unnamed}  total_owned={len(existing)}"
        )
        return 0
    finally:
        uow.close()


if __name__ == "__main__":
    raise SystemExit(main())
