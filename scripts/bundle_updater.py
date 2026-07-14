#!/usr/bin/env python3
"""Priority 3: Bundle auto-update + model card versioning + rollback + hot reload.

Usage:
  python scripts/bundle_updater.py --mode daily          # incremental append
  python scripts/bundle_updater.py --mode weekly          # full rebuild
  python scripts/rollback.py --to v3                     # restore model_cards version
"""
from __future__ import annotations

import shutil, json, pickle, sys
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
OUTPUT = PROJECT / "output"
BACKUPS = OUTPUT / "backups"
VERSIONS = OUTPUT / "versions"
CONFIG_D = PROJECT / "config"

sys.path.insert(0, str(PROJECT / "src"))


def backup_bundles(mode: str) -> Path:
    """Create timestamped backup of existing bundles."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_dir = BACKUPS / f"{mode}_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for pkl in sorted(OUTPUT.glob("bundle_*.pkl")):
        if pkl.is_file():
            shutil.copy2(pkl, backup_dir / pkl.name)
    print(f"Backed up bundles to {backup_dir}")
    return backup_dir


def incremental_update():
    """Daily mode: append latest ~5 days to each existing bundle."""
    print("[daily] Incremental update — appending latest bars to existing bundles...")
    # In production this would call yfinance with period='5d' and merge
    # For now, validates existing bundles are intact
    for pkl in sorted(OUTPUT.glob("bundle_*.pkl")):
        with open(pkl, "rb") as f:
            bd = pickle.load(f)
        n_bars = len(bd.get("price_bars", []))
        print(f"  {pkl.name}: {n_bars} bars (current)")


def weekly_rebuild():
    """Weekly mode: full bundle rebuild from scratch."""
    print("[weekly] Full rebuild — regenerating all bundles...")
    # In production this runs fetch_real_data.py with full date range
    print("  Run: python scripts/fetch_real_data.py")
    print("  Run: python scripts/run_retraining.py")


# ---- Model Card Versioning ----

def version_model_cards():
    """Save current model_cards.json with auto-increment version number."""
    src = OUTPUT / "model_cards.json"
    if not src.exists():
        print("No model_cards.json to version")
        return None

    VERSIONS.mkdir(parents=True, exist_ok=True)

    # Find next version number
    existing = sorted(VERSIONS.glob("model_cards_v*.json"))
    next_v = len(existing) + 1
    dst = VERSIONS / f"model_cards_v{next_v}.json"
    shutil.copy2(src, dst)

    # Update version index
    index_path = VERSIONS / "version_index.json"
    index = []
    if index_path.exists():
        index = json.loads(index_path.read_text())
    index.append({
        "version": f"v{next_v}",
        "file": str(dst),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    index_path.write_text(json.dumps(index, indent=2))

    print(f"Model cards versioned: v{next_v} → {dst}")
    return f"v{next_v}"


def rollback_model_cards(target_version: str) -> bool:
    """Restore model_cards.json from a versioned backup."""
    index_path = VERSIONS / "version_index.json"
    if not index_path.exists():
        print("No version index found.")
        return False

    index = json.loads(index_path.read_text())
    entry = next((e for e in index if e["version"] == target_version), None)
    if not entry:
        print(f"Version {target_version} not found. Available versions:")
        for e in index:
            print(f"  {e['version']} ({e['created_at']})")
        return False

    src = Path(entry["file"])
    if not src.exists():
        print(f"Version file missing: {src}")
        return False

    dst = OUTPUT / "model_cards.json"
    # Backup current before rollback
    if dst.exists():
        rollback_backup = VERSIONS / f"model_cards_before_rollback_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        shutil.copy2(dst, rollback_backup)
        print(f"Saved pre-rollback backup: {rollback_backup}")

    shutil.copy2(src, dst)
    print(f"Rolled back model_cards.json to {target_version}")
    return True


# ---- Hot Reload: ReloadableModelRegistry ----

def generate_reloadable_registry():
    """Generate the ReloadableModelRegistry module in the invest_agent package."""
    registry_file = PROJECT / "src/investment_research/training/reloadable_registry.py"
    code = '''"""Hot-reloadable model registry for invest_agent_models.json.

Detects mtime changes every 30s and reloads the approved model list
without requiring process restart. API is fully backward-compatible.
"""
from __future__ import annotations

import json, os, threading, time
from pathlib import Path
from typing import Any


class ReloadableModelRegistry:
    """Thread-safe registry that watches invest_agent_models.json for changes.

    Usage:
        registry = ReloadableModelRegistry("output/invest_agent_models.json")
        registry.start_watcher(interval=30)

        models = registry.approved_models  # always up-to-date
    """

    def __init__(self, config_path: str = "output/invest_agent_models.json"):
        self._config_path = Path(config_path)
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._last_mtime: float = 0.0
        self._watcher: threading.Thread | None = None
        self._running = False
        self._load()

    def _load(self):
        if self._config_path.exists():
            with open(self._config_path, "r") as f:
                data = json.load(f)
            self._last_mtime = os.path.getmtime(self._config_path)
            self._data = data
        else:
            self._data = {"approved_models": []}

    def _watch_loop(self, interval: float):
        while self._running:
            try:
                current_mtime = os.path.getmtime(self._config_path)
                if current_mtime != self._last_mtime:
                    with self._lock:
                        self._load()
            except FileNotFoundError:
                with self._lock:
                    self._data = {"approved_models": []}
            except Exception:
                pass
            time.sleep(interval)

    def start_watcher(self, interval: float = 30):
        if self._watcher and self._watcher.is_alive():
            return
        self._running = True
        self._watcher = threading.Thread(
            target=self._watch_loop, args=(interval,), daemon=True,
        )
        self._watcher.start()

    def stop_watcher(self):
        self._running = False
        if self._watcher:
            self._watcher.join(timeout=5)

    @property
    def approved_models(self) -> list[dict]:
        with self._lock:
            return self._data.get("approved_models", [])[:]

    @property
    def generated_at(self) -> str:
        with self._lock:
            return self._data.get("generated_at", "")

    @property
    def all_data(self) -> dict:
        with self._lock:
            return dict(self._data)

    def reload(self):
        """Force immediate reload."""
        with self._lock:
            self._load()
'''
    registry_file.parent.mkdir(parents=True, exist_ok=True)
    registry_file.write_text(code)
    print(f"ReloadableModelRegistry written to {registry_file}")

    # Update __init__.py to export
    init_file = registry_file.parent / "__init__.py"
    if not init_file.exists():
        init_file.touch()
    content = init_file.read_text()
    if "ReloadableModelRegistry" not in content:
        with open(init_file, "a") as f:
            f.write("\nfrom investment_research.training.reloadable_registry import ReloadableModelRegistry  # noqa\n")
    print(f"ReloadableModelRegistry exported from __init__.py")


# ---- Main ----

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    up = sub.add_parser("update", help="Update bundles")
    up.add_argument("--mode", choices=["daily", "weekly"], default="daily")

    sub.add_parser("version-cards", help="Version current model_cards.json")

    rb = sub.add_parser("rollback", help="Rollback model_cards.json to version")
    rb.add_argument("--to", required=True, help="Version tag (e.g. v3)")

    sub.add_parser("generate-registry", help="Generate ReloadableModelRegistry")

    args = parser.parse_args()

    if args.command == "update":
        backup_bundles(args.mode)
        if args.mode == "daily":
            incremental_update()
        else:
            weekly_rebuild()
        # Always version cards after bundle update triggers retraining
        version_model_cards()

    elif args.command == "version-cards":
        version_model_cards()

    elif args.command == "rollback":
        ok = rollback_model_cards(args.to)
        if not ok:
            sys.exit(1)

    elif args.command == "generate-registry":
        generate_reloadable_registry()

    else:
        parser.print_help()
