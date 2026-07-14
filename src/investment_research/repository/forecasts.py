from __future__ import annotations

from investment_research.domain.forecasts import ResearchForecastBundle


class ResearchForecastRepository:
    def __init__(self, connection) -> None:
        self.connection = connection

    def add(self, item: ResearchForecastBundle) -> ResearchForecastBundle:
        self.connection.execute(
            "INSERT OR REPLACE INTO research_forecast_bundles (id,analysis_run_id,asset_id,as_of,payload_json) VALUES (?,?,?,?,?)",
            (str(item.id), str(item.analysis_run_id), str(item.asset_id), item.as_of.isoformat(), item.model_dump_json()),
        )
        self.connection.commit()
        return item

    def for_run(self, run_id: str) -> ResearchForecastBundle | None:
        row = self.connection.execute("SELECT payload_json FROM research_forecast_bundles WHERE analysis_run_id=?", (run_id,)).fetchone()
        return None if row is None else ResearchForecastBundle.model_validate_json(str(row[0]))
