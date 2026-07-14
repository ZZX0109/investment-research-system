CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    entity_version INTEGER NOT NULL,
    data_mode TEXT NOT NULL,
    source_type TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_assets_source_type ON assets(source_type);
CREATE INDEX IF NOT EXISTS idx_assets_observed_at ON assets(observed_at);

CREATE TABLE IF NOT EXISTS evidence (
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

CREATE INDEX IF NOT EXISTS idx_evidence_asset_id ON evidence(asset_id);
CREATE INDEX IF NOT EXISTS idx_evidence_observed_at ON evidence(observed_at);

CREATE TABLE IF NOT EXISTS analysis_runs (
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

CREATE INDEX IF NOT EXISTS idx_analysis_runs_asset_id ON analysis_runs(asset_id);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_observed_at ON analysis_runs(observed_at);
