# AGENTS.md

> **This project was built with AI assistance.**
> Tool: **Devin** (interactive coding agent by Cognition), powered by model **SWE-2**.
> Date: 2026-10-01. Human requirements and review were provided in German; the
> codebase, docs and UI are in English (with a German UI translation included).

This file documents the requirements, architecture and rules for anyone (human
or agent) working on this repository.

## Purpose

`find-the-needle-saves` is a savegame manager for the Steam demo
**"Find the Needle"** (internal Godot name: *Haystack Incremental*). The demo
has no Steam Cloud save sync, so this tool provides:

- **Versioned backups** of the savegame (append-only, nothing is ever deleted)
- A **strictly increasing version number** — every change creates a new version
- A detailed **changelog** (`CHANGELOG.md` + `manifest.json` + `changelog.jsonl`
  inside the vault)
- **Folder-based sync** between computers (point the tool at any synced folder —
  Nextcloud, Google Drive, Syncthing, USB stick; the tool only needs a path)
- **Automatic backups** when the savegame changes (file watcher, polling)
- **Game settings editor** for `settings.cfg` + stability presets, because the
  game crashes / has startup issues and needs pre-launch tweaks
- **Log viewer + diagnostics** with hints for known problems

## Hard requirements (do not regress)

1. **Never delete or overwrite versions.** Vaults are append-only. Restore
   always creates a `pre-restore` safety snapshot first.
2. **Settings are machine-specific.** Snapshots always contain
   `settings.cfg`/`audio.cfg`, but restore only writes them back when the
   user explicitly opts in (`include_settings`). When they are applied, a
   targeted settings-only backup (`pre-settings-restore`) is created first.
3. **Version number always increments** on every change (backup, auto-backup,
   restore-safety, settings change, sync import) and is shown prominently in
   the GUI header.
4. **Changelog is always updated** — `CHANGELOG.md` is regenerated and shown
   in the UI after every change.
5. **Sync is path-only.** No network code, no credentials, no cloud APIs.
   Deduplication between machines happens via per-version UUIDs; imported
   versions get the next free local number and keep an `origin` reference.
   Diverged vaults trigger a decision dialog; entries get a `conflict`
   marker recording the alternative version.
6. **The latest savegame must always be identifiable** (highest version number
   in the merged view).
7. **`shader_cache/` is never backed up** (large, regenerable).
8. **Secrets stay out of the repo.** Runtime config lives in
   `%APPDATA%/needle-saves/config.json` (Linux/macOS: `~/.config/needle-saves/`),
   never in the repository. `.gitignore` excludes `.env`, `config.json`,
   vaults and `*.dat` saves. The game's `profile.cfg [identity]` section holds
   tokens — sync snapshots can redact them
   (`redact_identity_tokens_in_sync`, default: on).
9. **Game path auto-detection** per current OS user:
   `%APPDATA%/Godot/app_userdata/Haystack Incremental` (Windows),
   `~/Library/Application Support/Godot/app_userdata/` (macOS),
   `~/.local/share/godot/app_userdata/` (Linux). Overridable in Options.
10. **i18n**: all UI strings via `tr()` + JSON files in
   `src/needle_saves/locales/`. English is the fallback, German is included.
   Add a language by dropping in `<lang>.json`.
11. **Distribution**: single self-contained Windows client built with
    PyInstaller (`find_the_needle_saves.spec`, `scripts/build.bat`).

## Layout

```
src/needle_saves/
  __init__.py        - __version__, app name
  app.py             - entry point (QApplication)
  config.py          - user config outside the repo
  game.py            - game data dir discovery, snapshot file set, logs
  store.py           - VersionStore: manifest, zips, changelog, restore
  sync.py            - folder-based two-way sync (uuid dedupe, append-only)
  game_settings.py   - settings.cfg parser/writer, KNOWN_KEYS, PRESETS
  diagnostics.py     - log scanning -> hints mapped to presets
  i18n.py            - JSON locale loader
  locales/en.json    - English strings (fallback)
  locales/de.json    - German strings
  ui/main_window.py  - PySide6 main window (tabs: Saves/Settings/Logs/Options)
find_the_needle_saves.spec  - PyInstaller spec
scripts/build.bat           - Windows build helper
config.example.json         - documented config template (not used at runtime)
```

## Data formats

- Vault: `manifest.json` `{latest_version, entries[]}`; each entry has
  `version`, `uuid`, `created_at` (UTC ISO), `machine`, `action`, `note`,
  `filename`, `sha256`, `origin`.
- Snapshots are zips `versions/vNNNNNN-<uuid8>.zip` containing the game files
  (relative paths) plus `SNAPSHOT.json` metadata.
- `settings.cfg` is a Godot ConfigFile (INI with typed values like
  `Vector2i(...)`, `PackedStringArray(...)`, quoted strings). The settings
  editor preserves the raw file format.

## Conventions for agents

- Python 3.11+, PySide6 (Qt Widgets). Keep dependencies minimal.
- GUI language: English source, translated via `locales/*.json`.
- Run smoke tests headlessly where possible; Qt widgets can be instantiated
  with `QT_QPA_PLATFORM=offscreen`.
- Bump `__version__` in `src/needle_saves/__init__.py` when releasing.
