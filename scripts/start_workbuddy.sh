#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$(command -v python3 || command -v python)"
exec "$PYTHON_BIN" "$ROOT/scripts/start_workbuddy.py" "$@"
