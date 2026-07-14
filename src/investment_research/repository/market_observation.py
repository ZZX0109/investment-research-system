from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from investment_research.domain.market_models import DirectionalForecast, MarketQuote, MarketQuoteAttempt, ObservationRevision


class MarketObservationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def add_quote(self, quote: MarketQuote, payload: dict) -> MarketQuote:
        self.connection.execute(
            "INSERT INTO market_quotes VALUES (?,?,?,?,?,?,?,?,?)",
            (str(quote.id), str(quote.asset_id), quote.provider, quote.quote_at.isoformat(), quote.fetched_at.isoformat(), quote.last_price, quote.previous_close, quote.payload_hash, json.dumps(payload, ensure_ascii=False, default=str)),
        )
        self.connection.commit()
        return quote

    def latest_quote(self, asset_id: str) -> MarketQuote | None:
        row = self.connection.execute(
            "SELECT id,asset_id,provider,quote_at,fetched_at,last_price,previous_close,payload_hash FROM market_quotes WHERE asset_id=? ORDER BY quote_at DESC LIMIT 1", (asset_id,)
        ).fetchone()
        if row is None:
            return None
        return MarketQuote(id=row[0], asset_id=row[1], provider=row[2], quote_at=datetime.fromisoformat(str(row[3])), fetched_at=datetime.fromisoformat(str(row[4])), last_price=row[5], previous_close=row[6], payload_hash=row[7])

    def add_attempt(self, attempt: MarketQuoteAttempt) -> None:
        self.connection.execute(
            "INSERT INTO market_quote_attempts VALUES (?,?,?,?,?,?,?)",
            (str(attempt.id), str(attempt.asset_id), attempt.provider, attempt.state, attempt.attempted_at.isoformat(), attempt.error_code, attempt.error_message),
        )
        self.connection.commit()

    def latest_attempt(self, asset_id: str, provider: str) -> MarketQuoteAttempt | None:
        row = self.connection.execute(
            "SELECT id,asset_id,provider,state,attempted_at,error_code,error_message FROM market_quote_attempts WHERE asset_id=? AND provider=? ORDER BY attempted_at DESC LIMIT 1",
            (asset_id, provider),
        ).fetchone()
        if row is None:
            return None
        return MarketQuoteAttempt(id=row[0], asset_id=row[1], provider=row[2], state=row[3], attempted_at=datetime.fromisoformat(str(row[4])), error_code=row[5], error_message=row[6])

    def consecutive_failures(self, asset_id: str, provider: str | None = None) -> int:
        provider_clause = " AND provider=?" if provider else ""
        params = (asset_id, provider) if provider else (asset_id,)
        rows = self.connection.execute(
            f"SELECT state FROM market_quote_attempts WHERE asset_id=?{provider_clause} ORDER BY attempted_at DESC LIMIT 100", params
        ).fetchall()
        count = 0
        for row in rows:
            if str(row[0]) != "failed":
                break
            count += 1
        return count

    def add_revision(self, revision: ObservationRevision) -> ObservationRevision:
        existing = self.connection.execute(
            "SELECT 1 FROM observation_revisions WHERE observation_id=? AND revision=?",
            (str(revision.observation_id), revision.revision),
        ).fetchone()
        if existing is not None:
            raise ValueError("Observation revisions are immutable")
        self.connection.execute(
            "INSERT INTO observation_revisions (id,observation_id,revision,reason,payload_hash,payload_json,created_at) VALUES (?,?,?,?,?,?,?)",
            (str(revision.id), str(revision.observation_id), revision.revision, revision.reason, revision.payload_hash, json.dumps(revision.payload, ensure_ascii=False, default=str), revision.created_at.isoformat()),
        )
        self.connection.commit()
        return revision

    def revisions_for_observation(self, observation_id: str) -> list[ObservationRevision]:
        rows = self.connection.execute(
            "SELECT id,observation_id,revision,reason,payload_hash,payload_json,created_at FROM observation_revisions WHERE observation_id=? ORDER BY revision",
            (observation_id,),
        ).fetchall()
        return [
            ObservationRevision(
                id=row[0], observation_id=row[1], revision=row[2], reason=row[3], payload_hash=row[4],
                payload=json.loads(str(row[5])), created_at=datetime.fromisoformat(str(row[6])),
            )
            for row in rows
        ]

    def add_directional(self, item: DirectionalForecast) -> None:
        self.connection.execute(
            "INSERT INTO directional_forecasts VALUES (?,?,?,?,?,?)",
            (str(item.id), str(item.analysis_run_id), str(item.asset_id), item.status, item.model_dump_json(), datetime.now().astimezone().isoformat()),
        )
        self.connection.commit()

    def directional_for_run(self, run_id: str) -> DirectionalForecast | None:
        row = self.connection.execute("SELECT payload_json FROM directional_forecasts WHERE analysis_run_id=? ORDER BY created_at DESC LIMIT 1", (run_id,)).fetchone()
        return None if row is None else DirectionalForecast.model_validate_json(str(row[0]))
