CREATE TABLE IF NOT EXISTS watchlists (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    entity_version INTEGER NOT NULL,
    data_mode TEXT NOT NULL,
    source_type TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_watchlists_user_id ON watchlists(user_id);

CREATE TABLE IF NOT EXISTS price_series (
    id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    status TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    entity_version INTEGER NOT NULL,
    data_mode TEXT NOT NULL,
    source_type TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_price_series_asset_id ON price_series(asset_id);

CREATE TABLE IF NOT EXISTS research_reports (
    id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    analysis_run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    entity_version INTEGER NOT NULL,
    data_mode TEXT NOT NULL,
    source_type TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_reports_asset_id ON research_reports(asset_id);
CREATE INDEX IF NOT EXISTS idx_research_reports_analysis_run_id ON research_reports(analysis_run_id);
