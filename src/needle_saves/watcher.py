"""Change detection for automatic backups (GUI-agnostic, testable).

A snapshot is only taken when the game's save files actually changed - and
only once they have been stable for a full polling interval, so we never
capture a half-written save.
"""

from __future__ import annotations

from .game import GameData
from .store import VersionEntry, VersionStore


class AutoBackuper:
    def __init__(self, game: GameData, store: VersionStore,
                 enabled: bool = True) -> None:
        self.game = game
        self.store = store
        self.enabled = enabled
        self._last = game.save_files_signature() if game.exists else ()
        self._pending: tuple | None = None

    def mark_clean(self) -> None:
        """Call after actions that intentionally rewrote the save (restore)."""
        self._last = self.game.save_files_signature() if self.game.exists else ()
        self._pending = None

    def tick(self) -> VersionEntry | None:
        """Poll once. Returns the created entry if a backup was taken."""
        if not self.enabled or not self.game.exists:
            return None
        sig = self.game.save_files_signature()
        if sig == self._last:
            self._pending = None
            return None
        if self._pending == sig:
            # changed, and stable for one full interval -> snapshot once
            self._last = sig
            self._pending = None
            return self.store.create_version(
                self.game, "auto-backup", "automatic backup on change")
        self._pending = sig
        return None
