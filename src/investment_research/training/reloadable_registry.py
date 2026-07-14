"""Hot-reloadable model registry for invest_agent_models.json.

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
