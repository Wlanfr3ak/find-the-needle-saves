"""Discovery of the game's local data directory.

'Find the Needle' is a Godot game. Godot writes user data to
%APPDATA%/Godot/app_userdata/<project name>/ on Windows.
The demo's folder is called 'Haystack Incremental'.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

GAME_FOLDER_NAMES = ("Haystack Incremental", "Find the Needle Demo", "Find the Needle")

# Files that belong to a savegame snapshot. Relative to the game data dir.
SNAPSHOT_FILES = (
    "saves",
    "settings.cfg",
    "audio.cfg",
    "profile.cfg",
)

# Directories that are always excluded (large, regenerable, or noisy).
EXCLUDED_DIRS = ("shader_cache",)

# Machine-specific files: included in every snapshot, but only written back
# on restore when the user explicitly asks for it (different PCs may need
# different renderer/display settings).
SETTINGS_FILES = ("settings.cfg", "audio.cfg")

LOG_DIR = "logs"

# Keys inside profile.cfg -> [identity] that contain credentials/secrets.
IDENTITY_SECRET_KEYS = ("refresh_token", "access_token", "install_key")


def default_game_data_dir() -> Path | None:
    """Best-guess location of the game's user data, per current OS user."""
    if sys.platform == "win32":
        roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        base = roaming / "Godot" / "app_userdata"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "Godot" / "app_userdata"
    else:
        base = Path.home() / ".local" / "share" / "godot" / "app_userdata"

    for name in GAME_FOLDER_NAMES:
        candidate = base / name
        if candidate.is_dir():
            return candidate
    return base / GAME_FOLDER_NAMES[0] if base.is_dir() else None


@dataclass
class GameData:
    root: Path

    @property
    def saves_dir(self) -> Path:
        return self.root / "saves"

    @property
    def logs_dir(self) -> Path:
        return self.root / LOG_DIR

    @property
    def settings_file(self) -> Path:
        return self.root / "settings.cfg"

    @property
    def exists(self) -> bool:
        return self.root.is_dir()

    def snapshot_paths(self, include_logs: bool = False) -> list[Path]:
        """All files that make up a snapshot, relative paths preserved."""
        out: list[Path] = []
        for rel in SNAPSHOT_FILES:
            p = self.root / rel
            if p.is_dir():
                out.extend(sorted(f for f in p.rglob("*") if f.is_file()))
            elif p.is_file():
                out.append(p)
        if include_logs and self.logs_dir.is_dir():
            out.extend(sorted(f for f in self.logs_dir.rglob("*") if f.is_file()))
        return out

    def latest_log(self) -> Path | None:
        log = self.logs_dir / "godot.log"
        if log.is_file():
            return log
        logs = sorted(self.logs_dir.glob("*.log")) if self.logs_dir.is_dir() else []
        return logs[-1] if logs else None

    def all_logs(self) -> list[Path]:
        if not self.logs_dir.is_dir():
            return []
        return sorted(self.logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime)

    def save_files_signature(self) -> tuple[tuple[str, int, int], ...]:
        """(relative path, size, mtime_ns) for every snapshot file.

        Used by the auto-backup watcher to detect changes cheaply.
        """
        sig = []
        for f in self.snapshot_paths():
            try:
                st = f.stat()
            except OSError:
                continue
            sig.append((str(f.relative_to(self.root)), st.st_size, st.st_mtime_ns))
        return tuple(sorted(sig))

    def clear_shader_cache(self) -> int:
        """Delete the regenerable shader cache. Returns number of files removed."""
        cache = self.root / "shader_cache"
        if not cache.is_dir():
            return 0
        removed = 0
        for f in cache.rglob("*"):
            if f.is_file():
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
        for d in sorted((p for p in cache.rglob("*") if p.is_dir()),
                        key=lambda p: len(p.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
        try:
            cache.rmdir()
        except OSError:
            pass
        return removed
