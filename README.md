# Find the Needle — Save Manager

A savegame manager for the Steam demo **"Find the Needle"** (internal Godot
name: *Haystack Incremental*). The demo ships without Steam Cloud saves —
this tool gives you **versioned backups, a full changelog, automatic backups
and sync between computers via any synced folder**.

> **Built with AI:** this project was created with **Devin**, the coding agent
> by Cognition (model **SWE-2**), on 2026-10-01, from a German-language
> requirements spec. See `AGENTS.md` for the full requirement list and
> engineering rules.

## Features

- **Append-only versioned backups** — every snapshot is kept forever, the
  version number only ever counts up and is shown prominently in the header
  of the GUI (`Save version: v42`).
- **Detailed changelog** — every version records date (UTC), action, machine
  and an optional note; rendered as `CHANGELOG.md` in the vault and shown in
  the app.
- **Automatic backup** — a watcher notices when the game writes its save and
  creates a new version automatically.
- **Safe restore** — restoring a version first snapshots the current state
  (`pre-restore`), so nothing is ever lost. Machine-specific settings
  (`settings.cfg`, `audio.cfg`) are only applied when you tick the box in the
  restore dialog — and then the current settings are backed up first as a
  specially marked `pre-settings-restore` version.
- **Folder sync** — point the tool at a folder inside Nextcloud, Google
  Drive, Dropbox, Syncthing or a USB stick. Sync is strictly append-only and
  deduplicates across machines by UUID, so the newest save is always the
  highest version number. **No credentials or cloud APIs — just a path.**
- **Game settings editor** — the game (a Godot build) can crash or have
  startup issues. Edit `settings.cfg` keys (renderer, fullscreen, vsync,
  render thread, graphics, audio, autosave, …) or apply one-click
  **stability presets**. A backup is always created before any change.
- **Logs & Help** — browse the game's `logs/godot*.log` files; known problem
  patterns (experimental render thread, D3D12 issues, out of memory, shader
  errors) are detected and mapped to concrete fixes, incl. clearing the
  shader cache.
- **i18n ready** — English and German included; add a language by dropping a
  `<lang>.json` into `src/needle_saves/locales/`.
- **Privacy aware** — the game's `profile.cfg` contains an online identity
  section (tokens/install key). Synced snapshots can redact it (default on),
  and no runtime config or save data ever lives in this repository.

## What gets backed up

Everything that matters in `%APPDATA%\Godot\app_userdata\Haystack Incremental`:

| Included | Notes |
|---|---|
| `saves/` | `slot_0.dat`, `slot_0.dat.bak`, future slots |
| `settings.cfg` | game, display, graphics, HUD settings |
| `audio.cfg` | volume settings |
| `profile.cfg` | career stats + identity (optionally redacted in sync) |
| `logs/` | only if enabled in options |

**Excluded:** `shader_cache/` (large, regenerates automatically).

## Installation

### Prebuilt client

Grab `find-the-needle-saves.exe` from Releases — it's a single self-contained
PyInstaller build (Python + PySide6 included), no installation needed.

### From source

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m needle_saves
```

### Build the exe yourself (Windows)

```bat
scripts\build.bat
:: result: dist\find-the-needle-saves.exe
```

## Usage

1. Start the app. The game folder is auto-detected for the current user
   (`%APPDATA%\Godot\app_userdata\Haystack Incremental`).
2. **Savegames tab** — *Backup now* creates a version; select a row and
   *Restore selected* to roll back; the table + changelog show the full
   history. The big header always shows the latest version.
3. **Sync** — in *Options* set the *Sync folder* to a directory synced by
   your favourite tool (e.g. `D:\Nextcloud\NeedleSavesSync`). Press
   *Sync now* (or enable auto-sync on start). Repeat on your other PC —
   versions travel in both directions and never collide.
4. **Game settings tab** — tweak settings or hit a preset before launching
   the game. A backup version is created first.
5. **Logs & Help tab** — read the latest log, see detected problems and
   suggested fixes, clear the shader cache.

## Where data lives

| What | Where |
|---|---|
| User config | `%APPDATA%\needle-saves\config.json` (auto-created) |
| Local vault | `%APPDATA%\needle-saves\vault` (configurable) |
| Sync vault | wherever you point *Sync folder* at |
| Game data | `%APPDATA%\Godot\app_userdata\Haystack Incremental` |

Nothing inside this repository stores your saves — `*.dat`, vaults and
configs are git-ignored.

## Versioning model

```
vault/
  manifest.json          latest_version + all entries (version, uuid, sha256…)
  versions/v000001-<uuid>.zip   one zip per version — never deleted
  CHANGELOG.md           human-readable history, regenerated on every change
  changelog.jsonl        append-only machine log
```

Each version is a zip of the game data plus a `SNAPSHOT.json`. When syncing,
imported versions keep their origin (`machine`, original version) and get the
next free local number — the **highest number is always the newest save**.

## Development

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m needle_saves
```

- Bump `__version__` in `src/needle_saves/__init__.py` for releases.
- New language: copy `locales/en.json` to `locales/<lang>.json` and translate.
- See `AGENTS.md` for the hard rules (append-only, versioning, secrets).

## Disclaimer

Unofficial fan tool, not affiliated with the game's developer. Your saves are
your responsibility — this tool is deliberately conservative (append-only,
safety copies before every restore) but keep an external copy anyway.
