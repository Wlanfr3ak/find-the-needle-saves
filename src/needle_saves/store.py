"""Versioned snapshot store ("vault").

Layout of a vault directory:

    manifest.json        - machine-readable list of all versions
    versions/vNNNNNN-<uuid>.zip  - one zip per version, never deleted
    CHANGELOG.md         - human-readable, regenerated from the manifest
    changelog.jsonl      - append-only machine log

Rules (per user requirements):
- Every change creates a new version; the version number only ever increases.
- Nothing is ever deleted from a vault.
- Entries are deduplicated across machines by UUID so sync never double-imports.
"""

from __future__ import annotations

import getpass
import hashlib
import io
import json
import platform
import re
import uuid as uuidlib
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .game import IDENTITY_SECRET_KEYS, SETTINGS_FILES, GameData

MANIFEST_NAME = "manifest.json"
CHANGELOG_MD = "CHANGELOG.md"
CHANGELOG_JSONL = "changelog.jsonl"
VERSIONS_DIR = "versions"
SNAPSHOT_META = "SNAPSHOT.json"


def machine_id() -> str:
    return f"{platform.node() or 'unknown'}/{getpass.getuser() or 'user'}"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class VersionEntry:
    version: int
    uuid: str
    created_at: str
    machine: str
    action: str
    note: str
    filename: str
    sha256: str
    origin: dict = field(default_factory=dict)
    conflict: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "VersionEntry":
        return cls(
            version=int(d["version"]),
            uuid=d["uuid"],
            created_at=d.get("created_at", ""),
            machine=d.get("machine", ""),
            action=d.get("action", ""),
            note=d.get("note", ""),
            filename=d.get("filename", ""),
            sha256=d.get("sha256", ""),
            origin=d.get("origin", {}) or {},
            conflict=d.get("conflict", {}) or {},
        )

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "uuid": self.uuid,
            "created_at": self.created_at,
            "machine": self.machine,
            "action": self.action,
            "note": self.note,
            "filename": self.filename,
            "sha256": self.sha256,
            "origin": self.origin,
            "conflict": self.conflict,
        }


def redact_profile_cfg(data: bytes) -> bytes:
    """Blank credential values inside profile.cfg -> [identity]."""
    text = data.decode("utf-8", errors="replace")
    in_identity = False
    out_lines = []
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_identity = stripped == "[identity]"
        elif in_identity:
            for key in IDENTITY_SECRET_KEYS:
                if stripped.startswith(key + "="):
                    line = f'{key}=""\n'
                    break
        out_lines.append(line)
    return "".join(out_lines).encode("utf-8")


class VersionStore:
    """A vault of immutable, numbered savegame snapshots."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.versions_dir = root / VERSIONS_DIR
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path = root / MANIFEST_NAME
        self._entries: list[VersionEntry] | None = None

    # ---------------- manifest ----------------

    def _load(self) -> list[VersionEntry]:
        if self._entries is not None:
            return self._entries
        entries: list[VersionEntry] = []
        if self._manifest_path.is_file():
            try:
                data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
                entries = [VersionEntry.from_dict(e) for e in data.get("entries", [])]
            except (json.JSONDecodeError, OSError, KeyError):
                entries = []
        self._entries = sorted(entries, key=lambda e: e.version)
        return self._entries

    def _save(self) -> None:
        entries = self._load()
        data = {
            "app": "find-the-needle-saves",
            "latest_version": max((e.version for e in entries), default=0),
            "entries": [e.to_dict() for e in entries],
        }
        tmp = self._manifest_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(self._manifest_path)
        self._write_changelog_md()

    # ---------------- queries ----------------

    def entries(self) -> list[VersionEntry]:
        return list(self._load())

    def latest(self) -> VersionEntry | None:
        entries = self._load()
        return entries[-1] if entries else None

    def latest_version_number(self) -> int:
        latest = self.latest()
        return latest.version if latest else 0

    def known_uuids(self) -> set[str]:
        return {e.uuid for e in self._load()}

    def get(self, version: int) -> VersionEntry | None:
        for e in self._load():
            if e.version == version:
                return e
        return None

    def zip_path(self, entry: VersionEntry) -> Path:
        return self.versions_dir / entry.filename

    # ---------------- snapshot create ----------------

    def create_version(
        self,
        game: GameData,
        action: str,
        note: str = "",
        redact_identity: bool = False,
        only: tuple[str, ...] | None = None,
    ) -> VersionEntry:
        files = game.snapshot_paths(include_logs=False)
        if only is not None:
            files = [
                f for f in files
                if str(f.relative_to(game.root)).replace("\\", "/") in only
            ]
        meta = {
            "created_at": utcnow(),
            "machine": machine_id(),
            "action": action,
            "note": note,
            "files": [str(f.relative_to(game.root)) for f in files],
            "redacted": redact_identity,
        }
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(SNAPSHOT_META, json.dumps(meta, indent=2, ensure_ascii=False))
            for f in files:
                rel = str(f.relative_to(game.root)).replace("\\", "/")
                data = f.read_bytes()
                if redact_identity and rel == "profile.cfg":
                    data = redact_profile_cfg(data)
                zf.writestr(rel, data)
        return self._commit_zip(buf.getvalue(), action, note)

    def _commit_zip(self, payload: bytes, action: str, note: str,
                    origin: dict | None = None, entry_uuid: str | None = None,
                    created_at: str | None = None,
                    conflict: dict | None = None) -> VersionEntry:
        entries = self._load()
        uid = entry_uuid or uuidlib.uuid4().hex
        version = max((e.version for e in entries), default=0) + 1
        filename = f"v{version:06d}-{uid[:8]}.zip"
        zpath = self.versions_dir / filename
        zpath.write_bytes(payload)
        entry = VersionEntry(
            version=version,
            uuid=uid,
            created_at=created_at or utcnow(),
            machine=machine_id(),
            action=action,
            note=note,
            filename=filename,
            sha256=hashlib.sha256(payload).hexdigest(),
            origin=origin or {},
            conflict=conflict or {},
        )
        entries.append(entry)
        entries.sort(key=lambda e: e.version)
        self._entries = entries
        self._save()
        self._append_jsonl(entry)
        return entry

    def import_zip(self, payload: bytes, origin_entry: VersionEntry,
                   origin_vault: str, conflict: dict | None = None) -> VersionEntry:
        """Import a version coming from another vault (sync pull)."""
        return self._commit_zip(
            payload,
            action=origin_entry.action,
            note=origin_entry.note,
            origin={
                "machine": origin_entry.machine,
                "version": origin_entry.version,
                "vault": origin_vault,
            },
            entry_uuid=origin_entry.uuid,
            created_at=origin_entry.created_at,
            conflict=conflict,
        )

    def set_conflict(self, version: int, info: dict) -> None:
        """Attach/update conflict metadata on an existing entry."""
        entry = self.get(version)
        if entry is None:
            return
        entry.conflict.update(info)
        self._save()

    # ---------------- restore ----------------

    def create_settings_backup(self, game: GameData, note: str) -> VersionEntry:
        """Targeted backup of only the machine-specific settings files."""
        return self.create_version(
            game, action="pre-settings-restore", note=note,
            only=SETTINGS_FILES)

    def restore(self, version: int, game: GameData, note: str = "",
                include_settings: bool = False) -> VersionEntry:
        entry = self.get(version)
        if entry is None:
            raise ValueError(f"unknown version {version}")
        zpath = self.zip_path(entry)
        if not zpath.is_file():
            raise FileNotFoundError(str(zpath))

        # Settings are machine-specific: they are only written back when
        # explicitly requested - and then we always take a targeted,
        # marked backup of the current settings first.
        if include_settings:
            self.create_settings_backup(
                game, note or f"settings backup before restoring v{version}")

        # Safety net: snapshot the current state before overwriting.
        safety = self.create_version(
            game, action="pre-restore",
            note=note or f"automatic backup before restoring v{version}",
        )

        game.root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zpath) as zf:
            for member in zf.namelist():
                if member == SNAPSHOT_META or member.endswith("/"):
                    continue
                if not include_settings and member in SETTINGS_FILES:
                    continue
                target = game.root / member
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(member))
        return safety

    # ---------------- changelog ----------------

    def _append_jsonl(self, entry: VersionEntry) -> None:
        line = json.dumps({"ts": utcnow(), **entry.to_dict()}, ensure_ascii=False)
        with open(self.root / CHANGELOG_JSONL, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def _write_changelog_md(self) -> None:
        entries = self._load()
        lines = [
            "# Savegame Changelog",
            "",
            f"Latest version: **v{self.latest_version_number()}** "
            f"({len(entries)} version(s) stored)",
            "",
            "| Version | Date (UTC) | Action | Machine | Note |",
            "|---------|------------|--------|---------|------|",
        ]
        for e in reversed(entries):
            note = e.note.replace("|", "\\|")
            origin = ""
            if e.origin:
                origin = f" (from {e.origin.get('machine', '?')} v{e.origin.get('version', '?')})"
            marker = " **conflict: alternative version existed**" if e.conflict else ""
            lines.append(
                f"| v{e.version} | {e.created_at} | {e.action}{origin}{marker} | {e.machine} | {note} |"
            )
        lines.append("")
        (self.root / CHANGELOG_MD).write_text("\n".join(lines), encoding="utf-8")

    # ---------------- misc ----------------

    def verify(self, entry: VersionEntry) -> bool:
        zpath = self.zip_path(entry)
        if not zpath.is_file():
            return False
        return hashlib.sha256(zpath.read_bytes()).hexdigest() == entry.sha256


def snapshot_diff(zip_a: Path, zip_b: Path) -> dict:
    """Compare two snapshot zips by file name + CRC.

    Returns {'added', 'removed', 'changed', 'unchanged'} - each a sorted
    list of relative file names. 'changed' = present in both but different
    content.
    """
    def members(p: Path) -> dict[str, tuple[int, int]]:
        with zipfile.ZipFile(p) as zf:
            return {
                i.filename: (i.CRC, i.file_size)
                for i in zf.infolist()
                if not i.is_dir() and i.filename != SNAPSHOT_META
            }

    a, b = members(zip_a), members(zip_b)
    common = a.keys() & b.keys()
    return {
        "added": sorted(set(b) - set(a)),
        "removed": sorted(set(a) - set(b)),
        "changed": sorted(k for k in common if a[k] != b[k]),
        "unchanged": sorted(k for k in common if a[k] == b[k]),
    }


def sanitize_filename(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)[:64]
