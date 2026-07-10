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
