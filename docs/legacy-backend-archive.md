# Legacy Backend Archive

`investment-research-system/backend` is frozen. It is not imported by the API,
startup script, or CI path. Its only supported purpose is read-only historical
data replay through `scripts/replay_legacy_backend.py`.

New product behavior belongs under `src/investment_research`. Do not add routes,
providers, training logic, or database writes to the archived backend.
