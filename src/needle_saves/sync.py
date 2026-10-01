"""Folder-based two-way sync.

The "remote" is just another vault directory inside a folder that the user
syncs with whatever they like (Nextcloud, Google Drive, Syncthing, a USB
stick, ...). We only need a filesystem path - no credentials, no API.

Both directions are append-only:
- PUSH: every local version whose UUID is unknown remotely is copied over
  and appended to the remote manifest with the next free remote number.
- PULL: same in reverse.

Nothing is ever deleted on either side. The highest local version number
after a sync is always the newest savegame.

Conflicts: if both vaults advanced independently (each has versions the
other doesn't know), the sync is "diverged". The caller decides what to do
via `decision`. Imported versions whose ancestry does not contain the
target vault's current head are marked with
`conflict = {"alternative": {...}}` so the history shows that an
alternative version existed at that point. The diverging entries that stay
in their own vault get the same marker pointing at the other side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .store import VersionEntry, VersionStore

DECISIONS = ("merge", "pull-only", "push-only", "cancel")


@dataclass
class SyncResult:
    pushed: list[int] = field(default_factory=list)   # remote version numbers created
    pulled: list[int] = field(default_factory=list)   # local version numbers created
    conflicted: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def detect_conflict(local: VersionStore, remote: VersionStore) -> dict:
    """How far apart are the two vaults?

    diverged = both sides hold versions the other doesn't know.
    """
    lu, ru = local.known_uuids(), remote.known_uuids()
    local_only = [e for e in local.entries() if e.uuid not in ru]
    remote_only = [e for e in remote.entries() if e.uuid not in lu]
    return {
        "diverged": bool(local_only and remote_only),
        "local_only": local_only,
        "remote_only": remote_only,
        "local_latest": local.latest(),
        "remote_latest": remote.latest(),
    }


def _alt_info(entry: VersionEntry | None) -> dict:
    if entry is None:
        return {}
    return {
        "machine": entry.machine,
        "version": entry.version,
        "uuid": entry.uuid,
        "created_at": entry.created_at,
    }


def _conflict_for(source: VersionStore, target: VersionStore,
                  entry: VersionEntry) -> dict | None:
    """If the target vault's head is not an ancestor of `entry`, the import
    represents an alternative line -> return the conflict marker."""
    head = target.latest()
    if head is None:
        return None
    ancestors = {x.uuid for x in source.entries() if x.version < entry.version}
    if head.uuid not in ancestors:
        return {"alternative": _alt_info(head)}
    return None


def sync(local: VersionStore, remote_dir: Path,
         decision: str = "merge") -> SyncResult:
    result = SyncResult()
    if decision == "cancel":
        return result
    remote_dir.mkdir(parents=True, exist_ok=True)
    remote = VersionStore(remote_dir)

    info = detect_conflict(local, remote)
    result.conflicted = info["diverged"]
    local_only = list(info["local_only"])
    remote_only = list(info["remote_only"])
    local_top = max(local_only, key=lambda e: e.version, default=None)
    remote_top = max(remote_only, key=lambda e: e.version, default=None)

    # PUSH local -> remote
    if decision in ("merge", "push-only"):
        for entry in local_only:
            zpath = local.zip_path(entry)
            if not zpath.is_file():
                result.errors.append(f"missing zip for local v{entry.version}")
                continue
            conflict = _conflict_for(local, remote, entry)
            try:
                new = remote.import_zip(zpath.read_bytes(), entry,
                                        origin_vault=str(local.root),
                                        conflict=conflict)
                result.pushed.append(new.version)
            except OSError as exc:
                result.errors.append(f"push v{entry.version}: {exc}")

    # PULL remote -> local
    if decision in ("merge", "pull-only"):
        for entry in remote_only:
            zpath = remote.zip_path(entry)
            if not zpath.is_file():
                result.errors.append(f"missing zip for remote v{entry.version}")
                continue
            conflict = _conflict_for(remote, local, entry)
            try:
                new = local.import_zip(zpath.read_bytes(), entry,
                                       origin_vault=str(remote.root),
                                       conflict=conflict)
                result.pulled.append(new.version)
            except OSError as exc:
                result.errors.append(f"pull v{entry.version}: {exc}")

    # Mark the diverging entries that stayed in their own vault, so the
    # history on both sides shows an alternative version existed.
    if info["diverged"]:
        for e in local_only:
            local.set_conflict(e.version, {"alternative": _alt_info(remote_top)})
        for e in remote_only:
            remote.set_conflict(e.version, {"alternative": _alt_info(local_top)})

    return result


def remote_status(local: VersionStore, remote_dir: Path) -> dict:
    """How far apart are local and remote? Used for the status line."""
    if not remote_dir.is_dir():
        return {"available": False, "local_only": 0, "remote_only": 0}
    remote = VersionStore(remote_dir)
    lu, ru = local.known_uuids(), remote.known_uuids()
    return {
        "available": True,
        "local_only": len(lu - ru),
        "remote_only": len(ru - lu),
        "remote_latest": remote.latest_version_number(),
    }
