# Test Officer RBAC

The Test Officer API now has three access layers:

- Agent token: platform administrator access through `x-test-officer-token`.
- Run token: run-scoped read/download access through `x-test-officer-run-token`.
- Project token: project-scoped RBAC access through `x-test-officer-project-token`.

## Project Roles

Project tokens are HMAC-signed and scoped to one project id.
They expire using the same signing TTL as run-scoped tokens.

Roles:

- `viewer`: read-oriented project access.
- `operator`: can execute project operations such as artifact integrity checks, retention jobs, and download bundle preparation.
- `admin`: reserved for future project administration and secret rotation flows.

Sensitive storage operations now require either:

- a valid agent token, or
- a project token for the run's project with at least `operator` role.

Run tokens are not accepted for these write-adjacent operations.
They remain scoped to run reads/downloads.

Audit views support project-scoped read access:

- agent tokens can inspect global audit status and enumerate all audit runs
- project tokens with `viewer` or higher can list audit runs only when `project_id` is provided for the same project
- project tokens with `viewer` or higher can read audit detail for runs whose stored audit project id matches the token scope
- project tokens cannot globally enumerate audit runs without a project filter

## Protected Operations

The following endpoints enforce project operator access:

- `POST /api/v1/test-officer/runs/{run_id}/retention-job`
- `POST /api/v1/test-officer/runs/{run_id}/integrity`
- `POST /api/v1/test-officer/runs/{run_id}/download-bundle`

Negative tests cover:

- viewer project token accepted for same-project audit list/detail
- viewer project token rejected for global audit enumeration
- viewer project token rejected for operator endpoints
- project token scoped to another project rejected
- run token rejected for operator endpoints
- browser CORS preflight allows the project token header

## Why This Matters

The platform can keep a global agent token for CI/automation while letting project-level operators run storage and evidence maintenance on their own project without granting access to every run bundle.
This is a first step toward full multi-user RBAC and per-project isolation.
