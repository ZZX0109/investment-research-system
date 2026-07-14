# Phase 1 Foundation

This document translates the product goal into implementation boundaries.

## Domain backbone established

Every core business object now inherits the same backbone:

- `status`: lifecycle state such as `active`, `stale`, or `superseded`
- `version`: `schema_version` plus `entity_version`
- `provenance`: `data_mode`, `source_type`, `source_name`, `observed_at`, `confidence`, and `generation_chain`

That means the system can represent:

- real market data
- synthetic demo and sandbox data
- backfilled historical data
- manual overrides

without hiding the distinction inside ad hoc fields.

## Persistence boundary now in place

The repository layer now has a concrete first implementation:

- `repository/contracts.py` defines application-facing persistence interfaces
- `repository/sqlite.py` provides a SQLite unit of work plus migration bootstrap
- `migrations/001_initial.sql` locks the first durable table contract for assets, evidence, and analysis runs

This keeps services from reaching into SQL directly and creates a clean future swap point for PostgreSQL.

## Auth boundary now in place

The backend now has a first production-shaped auth slice:

- `auth/security.py` handles bcrypt password hashing and signed access/refresh tokens
- `auth/service.py` owns registration, login, refresh rotation, identity lookup, and logout revocation
- `api/auth_routes.py` exposes httpOnly cookie-based auth endpoints
- `migrations/002_auth.sql` persists users and refresh sessions separately from business entities
- `INVESTMENT_RESEARCH_PREVIOUS_SECRET_KEYS` provides a deployment rotation window: existing access/refresh tokens signed by previous secrets can be verified, while newly issued tokens are signed only by the active `INVESTMENT_RESEARCH_SECRET_KEY`
- Signed CSRF double-submit checks protect unsafe cookie-authenticated routes: the CSRF cookie, `x-csrf-token` header, and access/refresh token `csrf` claim must all match
- Cookie `Secure`/`SameSite` settings fail closed for unsafe production combinations

## User-bound write flows now in place

Business writes no longer float without identity context:

- `api/routes.py` now requires authenticated users for asset creation, position creation, and persisted analysis runs
- `service/workbench.py` records user-scoped `AuditRecord` entries for those writes
- `migrations/003_positions_and_audit.sql` persists `Position` and `AuditRecord`
- `GET /api/v1/positions/me` and `GET /api/v1/audit-records/me` provide user-scoped read models
- Analysis-run detail, bundle, comparison, replay, dossier, lineage-detail, scope, report generation, refresh status, and asset run lineage now require the authenticated owner; non-owner access is returned as not found

## Research workflow storage now in place

The typed research path now extends beyond assets and positions:

- `migrations/004_research_workflow.sql` persists `Watchlist`, `PriceSeries`, and `ResearchReport`
- `repository/sqlite.py` now stores user-scoped watchlists plus asset-scoped price series, evidence, and reports
- `api/routes.py` exposes APIs for watchlists, price series, evidence, and reports
- `service/workbench.py` keeps the business logic in one place and records audit entries for research writes

## Analysis pipeline now in place

The project now has a first reusable run pipeline instead of only CRUD:

- `pipeline/service.py` builds a persisted `AnalysisRun` bundle from stored asset, price, and evidence data
- `migrations/005_analysis_pipeline.sql` persists input snapshots, predictions, risk conclusions, recommendations, and judge scores
- `report/service.py` generates a `ResearchReport` from a fixed run bundle instead of mutable current state
- `api/routes.py` now exposes trigger, bundle retrieval, and fixed-run report generation endpoints

## Frontend workbench now in place

The frontend has moved beyond a placeholder shell:

- `workbench-ui/src/pages`, `features`, `components`, `hooks`, `api`, and `state` now separate page layout, business UI, primitives, data fetching, API access, and local UI state
- `@tanstack/react-query` handles server-state queries and mutations
- `zustand` manages lightweight UI state such as current mode and selected asset/run
- demo mode exposes stable synthetic/backfilled sample data, while live mode targets the FastAPI backend

## Phase-to-package mapping

### Phase 1

- Expand `domain/` with tighter validation and object relationships
- Add JSON schema export if external contracts need to be published
- Introduce repository interfaces once persistence rules are stable

### Phase 2

- Move database access into `repository/`
- Upgrade migration handling from bootstrap SQL files to Alembic or an equivalent tracked workflow
- Add `auth/` password hashing and token/session primitives
- Keep `api/` thin and route all orchestration through `service/`

### Phase 3

- Add data mode selection and visible source labeling in API responses
- Implement explicit demo, sandbox, and real-data repositories/pipelines

### Phase 4

- Build `pipeline/` around immutable `AnalysisRun`
- Generate reports from stored run snapshots in `report/`
- Turn Judge output into gating logic rather than display-only metadata

### Phase 5

- Add a frontend package that mirrors backend boundaries:
  - `pages`
  - `features`
  - `components`
  - `hooks`
  - `api`
  - `state`

## Immediate next moves

1. Add Alembic or an equivalent migration tool before tables start drifting
2. Add a deployment-facing admin flow for auth secret rotation scheduling and post-rotation previous-secret removal
3. Expand the frontend workbench from the current dashboard into a fuller multi-step workflow for evidence intake and report history
4. Expand the pipeline beyond heuristics toward pluggable ML/Judge components with explicit model/version registries
