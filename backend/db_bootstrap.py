from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Callable


MIGRATIONS_DIR = Path(__file__).with_name("migrations")
MIGRATION_DIRECTIVE_PREFIX = "-- investment_research:ensure_column "


DEFAULT_HOLDINGS = [
    {"symbol": "NVDA", "name": "NVIDIA", "market": "us", "sector": "AI 算力", "shares": 60.0, "costValue": 49500.0, "marketValue": 70200.0, "dayChange": 2.46},
    {"symbol": "TSLA", "name": "Tesla", "market": "us", "sector": "电动车", "shares": 90.0, "costValue": 21600.0, "marketValue": 23850.0, "dayChange": -1.18},
    {"symbol": "QQQ", "name": "Nasdaq 100 ETF", "market": "us", "sector": "科技指数", "shares": 110.0, "costValue": 43800.0, "marketValue": 55200.0, "dayChange": 0.74},
    {"symbol": "XLE", "name": "Energy Select ETF", "market": "us", "sector": "能源对冲", "shares": 220.0, "costValue": 17600.0, "marketValue": 35100.0, "dayChange": -0.42},
    {"symbol": "600519", "name": "贵州茅台", "market": "cn", "sector": "消费龙头", "shares": 10.0, "costValue": 16500.0, "marketValue": 15880.0, "dayChange": -0.36},
    {"symbol": "510300", "name": "沪深300 ETF", "market": "cn", "sector": "宽基指数", "shares": 3000.0, "costValue": 10800.0, "marketValue": 11370.0, "dayChange": 0.28},
]


SCHEMA_SQL = """
create table if not exists holdings (
  symbol text primary key,
  name text not null,
  market text not null,
  sector text not null,
  shares real not null,
  cost_value real not null,
  market_value real not null,
  day_change real not null
);

create table if not exists evidence_records (
  id integer primary key autoincrement,
  symbol text not null,
  claim text not null,
  source_type text not null,
  source_name text not null,
  source_url text,
  observed_at text not null,
  valid_until text not null,
  confidence real not null,
  is_model_inferred integer not null,
  superseded_by integer,
  archived_at text
);

create table if not exists experience_history (
  id integer primary key autoincrement,
  symbol text not null,
  archived_claim text not null,
  source_type text not null,
  observed_at text not null,
  archived_at text not null,
  reason text not null
);

create table if not exists historical_prices (
  symbol text not null,
  trade_date text not null,
  close_price real not null,
  volume real not null,
  source_name text not null default 'synthetic_demo_price_path',
  primary key(symbol, trade_date)
);

create table if not exists user_preferences (
  id integer primary key check (id = 1),
  preference text not null
);

create table if not exists research_runs (
  run_id text primary key,
  symbol text not null,
  preference text not null,
  started_at text not null,
  finished_at text not null,
  data_status text not null,
  risk_score real not null,
  summary text not null,
  input_snapshot_hash text,
  input_snapshot_json text,
  model_version text,
  evidence_ids_json text,
  reasoning_steps_json text,
  judge_json text,
  risk_conclusion_json text,
  report_version text,
  source_meta_json text
);

create table if not exists report_snapshots (
  run_id text primary key,
  symbol text not null,
  preference text not null,
  report_version text not null,
  markdown text not null,
  created_at text not null
);

create table if not exists multimodal_documents (
  document_id text primary key,
  symbol text not null,
  filename text not null,
  uploaded_at text not null,
  source_type text not null,
  text_blocks integer not null,
  table_blocks integer not null,
  chart_blocks integer not null,
  footnote_blocks integer not null default 0,
  summary text not null
);

create table if not exists document_blocks (
  id integer primary key autoincrement,
  document_id text not null,
  symbol text not null,
  block_type text not null,
  label text not null,
  locator text not null,
  content_preview text not null,
  created_at text not null
);

create table if not exists financial_metrics (
  id integer primary key autoincrement,
  document_id text not null,
  symbol text not null,
  metric_name text not null,
  metric_value text not null,
  period text not null,
  source_block text not null
);

create table if not exists report_settings (
  id integer primary key check (id = 1),
  frequency text not null,
  updated_at text not null
);

create table if not exists users (
  id integer primary key autoincrement,
  email text unique not null,
  password_hash text not null,
  salt text not null,
  created_at text not null,
  role text not null default 'user'
);

create table if not exists sessions (
  token text primary key,
  user_id integer not null,
  created_at text not null,
  expires_at text,
  refresh_token_hash text,
  refresh_expires_at text,
  revoked_at text
);

create table if not exists user_profiles (
  user_id integer primary key,
  preference text not null,
  risk_answers text not null,
  onboarding_completed integer not null,
  updated_at text not null
);

create table if not exists user_holdings (
  id integer primary key autoincrement,
  user_id integer not null,
  symbol text not null,
  name text not null,
  market text not null,
  sector text not null,
  shares real not null,
  cost_price real not null,
  updated_at text not null
);

create table if not exists api_keys (
  id integer primary key autoincrement,
  user_id integer not null,
  provider text not null,
  api_key text not null,
  updated_at text not null,
  unique(user_id, provider)
);

create table if not exists tool_registry (
  tool_id text primary key,
  name text not null,
  category text not null,
  description text not null,
  freshness_rule text not null,
  output_contract text not null,
  updated_at text not null
);

create table if not exists tool_invocations (
  id integer primary key autoincrement,
  run_id text not null,
  tool_id text not null,
  symbol text not null,
  input_json text not null,
  output_summary text not null,
  source_name text not null,
  observed_at text not null,
  status text not null,
  failure_reason text,
  evidence_id integer
);

create table if not exists evidence_refresh_runs (
  refresh_id text primary key,
  user_id integer not null,
  refreshed_at text not null,
  symbol_count integer not null,
  archived_count integer not null,
  summary text not null
);

create table if not exists evidence_refresh_items (
  id integer primary key autoincrement,
  refresh_id text not null,
  symbol text not null,
  before_score real not null,
  after_score real not null,
  risk_score_delta real not null,
  before_claim_summary text not null,
  after_claim_summary text not null,
  evidence_changes text not null,
  conclusion_changes text not null,
  snapshot_status text not null
);

create table if not exists model_registry (
  model_id text primary key,
  model_type text not null,
  version text not null,
  feature_version text not null,
  trained_until text not null,
  validation_window text not null,
  test_window text not null,
  metrics_json text not null,
  artifact_path text not null,
  status text not null default 'candidate',
  created_at text not null
);

create table if not exists feature_snapshots (
  id integer primary key autoincrement,
  symbol text not null,
  market text not null,
  as_of_date text not null,
  feature_version text not null,
  features_json text not null,
  source_status_json text not null,
  created_at text not null,
  unique(symbol, as_of_date, feature_version)
);

create table if not exists point_in_time_features (
  id integer primary key autoincrement,
  symbol text not null,
  market text not null,
  as_of_date text not null,
  feature_version text not null,
  field_name text not null,
  field_value_json text not null,
  source text not null,
  available_at text not null,
  revision_id text not null,
  created_at text not null,
  unique(symbol, as_of_date, feature_version, field_name, revision_id)
);

create table if not exists risk_predictions (
  id integer primary key autoincrement,
  symbol text not null,
  market text not null,
  as_of_date text not null,
  model_id text not null,
  horizon text not null,
  risk_regime text not null,
  drawdown_p50 real not null,
  drawdown_p90 real not null,
  volatility_p50 real not null,
  confidence real not null,
  calibration_status text not null,
  valid_until text not null,
  created_at text not null
);

create table if not exists scenario_embeddings (
  id integer primary key autoincrement,
  symbol text not null,
  market text not null,
  as_of_date text not null,
  window_size integer not null,
  model_id text not null,
  embedding_json text not null,
  source_status text not null,
  created_at text not null,
  unique(symbol, as_of_date, window_size, model_id)
);

create table if not exists similar_scenarios (
  id integer primary key autoincrement,
  query_symbol text not null,
  query_as_of_date text not null,
  matched_symbol text not null,
  matched_as_of_date text not null,
  similarity real not null,
  return_1w real not null,
  return_1m real not null,
  return_3m real not null,
  max_drawdown_1w real not null default 0,
  max_drawdown_1m real not null,
  max_drawdown_3m real not null,
  volatility_1m real not null default 0,
  model_id text not null,
  created_at text not null
);
"""


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"alter table {table} add column {column} {definition}")


def ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        create table if not exists schema_migrations (
          version text primary key,
          applied_at text not null default current_timestamp
        )
        """
    )


def apply_migration_file(conn: sqlite3.Connection, path: Path) -> None:
    sql_lines: list[str] = []
    ensure_directives: list[tuple[str, str, str]] = []
    for line in path.read_text().splitlines():
        if line.startswith(MIGRATION_DIRECTIVE_PREFIX):
            raw = line.removeprefix(MIGRATION_DIRECTIVE_PREFIX)
            table, column, definition = raw.split(" ", 2)
            ensure_directives.append((table, column, definition))
            continue
        sql_lines.append(line)

    sql = "\n".join(sql_lines).strip()
    if sql:
        conn.executescript(sql)
    for table, column, definition in ensure_directives:
        ensure_column(conn, table, column, definition)


def apply_migrations(conn: sqlite3.Connection) -> None:
    ensure_schema_migrations_table(conn)
    applied = {
        row["version"]
        for row in conn.execute("select version from schema_migrations").fetchall()
    }
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.stem
        if version in applied:
            continue
        apply_migration_file(conn, path)
        conn.execute("insert into schema_migrations(version) values(?)", (version,))


def seed_default_holdings(conn: sqlite3.Connection) -> None:
    existing = conn.execute("select count(*) as count from holdings").fetchone()["count"]
    if existing:
        return
    conn.executemany(
        """
        insert into holdings(symbol, name, market, sector, shares, cost_value, market_value, day_change)
        values(:symbol, :name, :market, :sector, :shares, :costValue, :marketValue, :dayChange)
        """,
        DEFAULT_HOLDINGS,
    )


def seed_default_user_preference(conn: sqlite3.Connection) -> None:
    row = conn.execute("select count(*) as count from user_preferences").fetchone()
    if int(row["count"]) == 0:
        conn.execute("insert into user_preferences(id, preference) values(1, 'balanced')")


def label_demo_seed_evidence(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        update evidence_records
        set claim = replace(claim, '最新价格和日内涨跌来自行情接口或演示缓存。', '行情证据槽位已创建；若实时接口失败，不能把缓存或成本价兜底当作最新市场事实。'),
            source_name = 'yfinance/AkShare live-first; cache clearly labeled',
            confidence = min(confidence, 0.62)
        where source_type = 'market_data'
          and source_name = 'yfinance/AkShare or local cache'
        """
    )
    conn.execute(
        """
        update evidence_records
        set claim = replace(claim, '财务与估值摘要需要随最新财报更新。', '财务与估值摘要待真实财报/公告接入；当前模板证据仅用于展示字段结构。'),
            source_name = 'demo placeholder until SEC/EDGAR/AkShare filing is attached',
            confidence = min(confidence, 0.38)
        where source_type = 'financial_report'
          and source_name = 'SEC/EDGAR, yfinance, AkShare'
        """
    )
    conn.execute(
        """
        update evidence_records
        set claim = replace(claim, '相关事件是当前风险解释的重要上下文。', '新闻事件待真实新闻源接入；当前模板不能作为事件事实。'),
            source_name = 'demo placeholder; public news source required',
            confidence = min(confidence, 0.32)
        where source_type = 'news_event'
          and source_name = 'public news summary cache'
        """
    )


def bootstrap_database(
    *,
    connect: Callable[[], sqlite3.Connection],
    updated_at: str,
    ensure_default_report_settings: Callable[..., None],
    register_standard_tools: Callable[[sqlite3.Connection], None],
    ensure_developer_account: Callable[[sqlite3.Connection], None],
) -> None:
    with closing(connect()) as conn:
        apply_migrations(conn)
        seed_default_holdings(conn)
        seed_default_user_preference(conn)
        ensure_default_report_settings(conn, updated_at=updated_at)
        register_standard_tools(conn)
        ensure_developer_account(conn)
        label_demo_seed_evidence(conn)
        conn.commit()


def refresh_seed_data(
    *,
    connect: Callable[[], sqlite3.Connection],
    ensure_price_history: Callable[[sqlite3.Connection, str, str | None], dict[str, Any]],
    ensure_evidence: Callable[[sqlite3.Connection, sqlite3.Row], None],
    archive_expired_evidence: Callable[[sqlite3.Connection], None],
) -> None:
    with closing(connect()) as conn:
        for holding in conn.execute("select * from holdings").fetchall():
            ensure_price_history(conn, holding["symbol"], holding["market"])
            ensure_evidence(conn, holding)
        archive_expired_evidence(conn)
        conn.commit()
