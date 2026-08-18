# Migration Workflow

The project now keeps a formal Alembic migration chain under `alembic/versions/`.

## Current runtime behavior

- `SQLiteUnitOfWork` now applies `alembic upgrade head` against its target SQLite database before opening repository access
- `alembic/versions/*.py` is the ordered migration chain used by both manual upgrades and runtime SQLite initialization
- `migrations/*.sql` is still referenced by the Alembic revision files as a transitional way to reuse the existing DDL blocks

This is closer to a single migration source, though the revision files still embed SQL from `migrations/*.sql`.

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
