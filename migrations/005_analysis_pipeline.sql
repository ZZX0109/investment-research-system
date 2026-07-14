CREATE TABLE IF NOT EXISTS analysis_snapshots (
    run_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS model_predictions (
    id TEXT PRIMARY KEY,
    analysis_run_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    status TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    entity_version INTEGER NOT NULL,
    data_mode TEXT NOT NULL,
    source_type TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_model_predictions_run_id ON model_predictions(analysis_run_id);

CREATE TABLE IF NOT EXISTS risk_conclusions (
    id TEXT PRIMARY KEY,
    analysis_run_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    status TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    entity_version INTEGER NOT NULL,
    data_mode TEXT NOT NULL,
    source_type TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_risk_conclusions_run_id ON risk_conclusions(analysis_run_id);

CREATE TABLE IF NOT EXISTS recommendations (
    id TEXT PRIMARY KEY,
    analysis_run_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    status TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    entity_version INTEGER NOT NULL,
    data_mode TEXT NOT NULL,
    source_type TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_recommendations_run_id ON recommendations(analysis_run_id);

CREATE TABLE IF NOT EXISTS judge_scores (
    id TEXT PRIMARY KEY,
    analysis_run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    entity_version INTEGER NOT NULL,
    data_mode TEXT NOT NULL,
    source_type TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_judge_scores_run_id ON judge_scores(analysis_run_id);
