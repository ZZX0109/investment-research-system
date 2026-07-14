CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    entity_version INTEGER NOT NULL,
    data_mode TEXT NOT NULL,
    source_type TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    payload TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS refresh_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_id TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_refresh_sessions_token_id ON refresh_sessions(token_id);
CREATE INDEX IF NOT EXISTS idx_refresh_sessions_user_id ON refresh_sessions(user_id);
