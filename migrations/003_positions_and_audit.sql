CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    asset_id TEXT NOT NULL,
    status TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    entity_version INTEGER NOT NULL,
    data_mode TEXT NOT NULL,
    source_type TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_positions_user_id ON positions(user_id);
CREATE INDEX IF NOT EXISTS idx_positions_asset_id ON positions(asset_id);

CREATE TABLE IF NOT EXISTS audit_records (
    id TEXT PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    status TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    entity_version INTEGER NOT NULL,
    data_mode TEXT NOT NULL,
    source_type TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_records_actor ON audit_records(actor);
CREATE INDEX IF NOT EXISTS idx_audit_records_target_id ON audit_records(target_id);
