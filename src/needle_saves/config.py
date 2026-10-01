"""Application configuration handling.

Config lives outside the repository so secrets/paths are never committed.
Location: %APPDATA%/needle-saves/config.json on Windows,
~/.config/needle-saves/config.json elsewhere.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from . import APP_ID

DEFAULTS: dict[str, Any] = {
    "game_data_dir": "",
    "vault_dir": "",
    "sync_dir": "",
    "language": "en",
    "auto_backup": True,
    "auto_backup_interval_seconds": 20,
    "auto_sync_on_start": False,
    "include_logs_in_snapshots": False,
    "restore_include_settings": False,
    "redact_identity_tokens_in_sync": True,
}

# Keys whose values must never be written into the repository copy.
SENSITIVE_KEYS = ("sync_dir",)


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_ID


def config_path() -> Path:
    return config_dir() / "config.json"


class Config:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_path()
        self._data: dict[str, Any] = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        if self.path.is_file():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data.update(loaded)
            except (json.JSONDecodeError, OSError):
                pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)
