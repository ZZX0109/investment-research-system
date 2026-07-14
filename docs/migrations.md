# Migration Workflow

The project now keeps a formal Alembic migration chain under `alembic/versions/`.

## Current runtime behavior

- `SQLiteUnitOfWork` now applies `alembic upgrade head` against its target SQLite database before opening repository access
- `alembic/versions/*.py` is the ordered migration chain used by both manual upgrades and runtime SQLite initialization
- `migrations/*.sql` is still referenced by the Alembic revision files as a transitional way to reuse the existing DDL blocks

This is closer to a single migration source, though the revision files still embed SQL from `migrations/*.sql`.

## Run bundle audit database

The Test Officer run database at `runs/audit/audit.sqlite` is versioned separately from the application database.

Runtime behavior:

- `src/platform/audit-store.ts` creates `audit_schema_migrations` before writing audit rows.
- Every run-bundle write applies the idempotent audit-store migrations and records their versions.
- `readAuditStoreStatus(...)` exposes `schemaVersion`, `schemaMigrationCount`, and `schemaAppliedAt`.
- `GET /api/v1/test-officer/audit/status` exposes the same fields through `RunBundleAuditStatus`.

Current audit-store chain:

1. `0001_core_run_bundle_audit`
2. `0002_connector_failure_runtime_signals`
3. `0003_project_scoped_artifact_metadata`

This gives CI and Workbench a concrete way to detect whether a local run DB can support project-scoped audit views, connector/failure attribution rows, encrypted artifact metadata, and large trace/video storage metadata.

## Apply migrations to a fresh database

```bash
python3 -m pip install -e ".[dev]"
export INVESTMENT_RESEARCH_DATABASE_URL="sqlite:///$(pwd)/var/alembic-dev.db"
alembic upgrade head
```

## Inspect current revision

```bash
export INVESTMENT_RESEARCH_DATABASE_URL="sqlite:///$(pwd)/var/alembic-dev.db"
alembic current
```

## Current chain

1. `0001_initial_schema`
2. `0002_auth_schema`
3. `0003_positions_and_audit`
4. `0004_research_workflow`
5. `0005_analysis_pipeline`
