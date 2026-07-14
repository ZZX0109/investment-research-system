#!/usr/bin/env bash
# Priority 1: Full regression pipeline — real data fetch → labels → tests → retrain
# Usage: bash scripts/run_full_regression.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT"

echo "=============================================="
echo " Full Regression Pipeline"
echo "=============================================="

# ---- 0. Environment ----
echo "[0/9] Resolving Python environment ..."
if [[ -x "$PROJECT/.venv/bin/python" ]]; then
  source "$PROJECT/.venv/bin/activate"
fi
PYTHON_BIN="$(command -v python3 || command -v python)"
export DYLD_LIBRARY_PATH="$PROJECT/lib:${DYLD_LIBRARY_PATH:-}"
echo "  Python=$PYTHON_BIN"
echo "  DYLD_LIBRARY_PATH=$DYLD_LIBRARY_PATH"

# ---- 1. Real Data ----
echo ""
echo "[1/9] Fetching real data (OHLCV) ..."
"$PYTHON_BIN" scripts/fetch_real_data.py

# ---- 2. Events ----
echo ""
echo "[2/9] Fetching real events (filings/announcements + earnings + news) ..."
"$PYTHON_BIN" scripts/fetch_real_events.py

# ---- 3. Benchmarks ----
echo ""
echo "[3/9] Fetching real benchmarks (sector/style) ..."
"$PYTHON_BIN" scripts/fetch_real_benchmarks.py

# ---- 4. Rebuild Labels ----
echo ""
echo "[4/9] Rebuilding labels from real data ..."
"$PYTHON_BIN" scripts/run_retraining.py --data-source real --profile full

# ---- 5. Tests ----
echo ""
echo "[5/9] Running full test suite ..."
"$PYTHON_BIN" -m pytest tests/ -v --tb=short

echo ""
echo "[6/9] Writing authoritative audits and paper simulation ..."
"$PYTHON_BIN" scripts/run_audits.py

echo ""
echo "[7/9] Running out-of-time feature ablation ..."
"$PYTHON_BIN" scripts/run_feature_ablation.py

echo ""
echo "[8/9] Serializing approved deployment models ..."
"$PYTHON_BIN" scripts/serialize_models.py

# ---- 6. Gate Scorecard ----
echo ""
echo "[9/9] Running gate scorecard ..."
"$PYTHON_BIN" -c "
import json
from pathlib import Path
p = Path('output/results.json')
if p.exists():
    r = json.load(open(p))
    eligible = [m for m in r.get('models', []) if m.get('eligible_for_approval')]
    print(f'Gate results: {len(eligible)}/{len(r.get(\"models\",[]))} models eligible')
    for m in eligible:
        print(f'  ELIGIBLE: {m[\"trainer_name\"]}')
else:
    print('No results.json — retraining may have failed')
"

echo ""
echo "=============================================="
echo " Pipeline Complete"
echo "=============================================="
echo "Outputs:"
ls -la "$PROJECT/output/" | grep -E 'bundle_|events_|benchmarks|results|evaluation|model_card|invest_agent' || true
echo ""
echo "Audits:"
ls -la "$PROJECT/audits/" || true
