"""Headless smoke test for the core logic (no GUI needed).

Run:  python tests/smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from needle_saves.game import GameData  # noqa: E402
from needle_saves.game_settings import GameSettings, apply_preset  # noqa: E402
from needle_saves.store import VersionStore, snapshot_diff  # noqa: E402
from needle_saves.sync import detect_conflict, remote_status, sync  # noqa: E402
from needle_saves.watcher import AutoBackuper  # noqa: E402
from needle_saves.diagnostics import analyze_log  # noqa: E402
from needle_saves.i18n import tr, set_language  # noqa: E402


def make_fake_game(root: Path) -> GameData:
    (root / "saves").mkdir(parents=True)
    (root / "logs").mkdir()
    (root / "shader_cache").mkdir()
    (root / "saves" / "slot_0.dat").write_bytes(b"GDEC-fake-save-v1")
    (root / "saves" / "slot_0.dat.bak").write_bytes(b"GDEC-fake-bak")
    (root / "settings.cfg").write_text(
        '[display]\n\nfullscreen=false\nrenderer="d3d12"\n\n'
        '[save]\n\nautosave=true\n', encoding="utf-8")
    (root / "audio.cfg").write_text('[audio]\n\nmaster=0.0\n', encoding="utf-8")
    (root / "profile.cfg").write_text(
        '[identity]\n\nrefresh_token="SECRET"\ninstall_key="KEY"\n',
        encoding="utf-8")
    (root / "logs" / "godot.log").write_text(
        "Godot Engine\nWARNING: The separate rendering thread feature is "
        "experimental.\n", encoding="utf-8")
    (root / "shader_cache" / "x.cache").write_bytes(b"x" * 1000)
    return GameData(root)


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        game = make_fake_game(td / "game")
        vault_a = VersionStore(td / "vault_a")
        vault_b_dir = td / "sync"

        # --- backup / versioning ---
        e1 = vault_a.create_version(game, "manual-backup", "first")
        assert e1.version == 1
        # shader cache must not be inside the zip
        import zipfile
        with zipfile.ZipFile(vault_a.zip_path(e1)) as zf:
            names = zf.namelist()
        assert not any("shader_cache" in n for n in names), names
        assert "saves/slot_0.dat" in names and "settings.cfg" in names

        (game.root / "saves" / "slot_0.dat").write_bytes(b"GDEC-v2")
        e2 = vault_a.create_version(game, "auto-backup")
        assert e2.version == 2
        assert vault_a.latest_version_number() == 2
        assert (vault_a.root / "CHANGELOG.md").is_file()
        assert "v2" in (vault_a.root / "CHANGELOG.md").read_text()

        # --- restore ---
        safety = vault_a.restore(1, game)
        assert safety.version == 3 and safety.action == "pre-restore"
        assert (game.root / "saves" / "slot_0.dat").read_bytes() == b"GDEC-fake-save-v1"

        # --- redaction ---
        e4 = vault_a.create_version(game, "manual-backup", redact_identity=True)
        with zipfile.ZipFile(vault_a.zip_path(e4)) as zf:
            prof = zf.read("profile.cfg").decode()
        assert 'refresh_token=""' in prof and 'install_key=""' in prof

        # --- sync both ways ---
        res = sync(vault_a, vault_b_dir)
        assert res.ok and len(res.pushed) == 4, res
        remote = VersionStore(vault_b_dir)
        assert remote.latest_version_number() == 4
        st = remote_status(vault_a, vault_b_dir)
        assert st["local_only"] == 0 and st["remote_only"] == 0

        # pretend vault_b is another machine that created a version
        (game.root / "saves" / "slot_0.dat").write_bytes(b"GDEC-other-pc")
        remote.create_version(game, "manual-backup", "from other pc")
        res = sync(vault_a, vault_b_dir)
        assert len(res.pulled) == 1
        imported = vault_a.latest()
        assert imported.version == 5 and imported.origin.get("machine")
        assert not imported.conflict  # fast-forward, no divergence

        # --- settings only restored on explicit request ---
        (game.root / "settings.cfg").write_text(
            '[display]\n\nfullscreen=true\nrenderer="vulkan"\n',
            encoding="utf-8")
        vault_a.restore(1, game)  # default: keep local settings
        assert 'renderer="vulkan"' in (game.root / "settings.cfg").read_text()
        assert (game.root / "saves" / "slot_0.dat").read_bytes() == \
            b"GDEC-fake-save-v1"
        # a plain restore creates no settings backup
        assert not any(e.action == "pre-settings-restore"
                       for e in vault_a.entries())

        # explicit opt-in: targeted marked settings backup + apply settings
        vault_a.restore(1, game, include_settings=True)
        assert 'renderer="d3d12"' in (game.root / "settings.cfg").read_text()
        sback = [e for e in vault_a.entries()
                 if e.action == "pre-settings-restore"]
        assert len(sback) == 1
        with zipfile.ZipFile(vault_a.zip_path(sback[0])) as zf:
            names = sorted(zf.namelist())
        assert names == ["SNAPSHOT.json", "audio.cfg", "settings.cfg"], names

        # --- auto-backup watcher: no backup without changes ---
        watcher = AutoBackuper(game, vault_a)
        for _ in range(10):
            assert watcher.tick() is None
        n_versions = len(vault_a.entries())

        # change -> first tick only marks pending, second tick backs up once
        (game.root / "saves" / "slot_0.dat").write_bytes(b"GDEC-changed")
        assert watcher.tick() is None            # seen, but not stable yet
        e = watcher.tick()
        assert e is not None and e.action == "auto-backup"
        # stable afterwards: no more backups, ever
        for _ in range(10):
            assert watcher.tick() is None
        assert len(vault_a.entries()) == n_versions + 1

        # mark_clean after a restore prevents a spurious backup
        vault_a.restore(e.version, game)
        watcher.mark_clean()
        assert watcher.tick() is None

        # --- conflict / divergence detection ---
        sync_dir2 = td / "sync2"
        # machine A vault
        va = VersionStore(td / "va")
        (game.root / "saves" / "slot_0.dat").write_bytes(b"GDEC-base")
        va.create_version(game, "manual-backup", "shared base")
        sync(va, sync_dir2)                      # both have v1
        vb = VersionStore(sync_dir2)

        # both sides advance independently -> diverged
        (game.root / "saves" / "slot_0.dat").write_bytes(b"GDEC-local-work")
        va.create_version(game, "manual-backup", "local progress")
        (game.root / "saves" / "slot_0.dat").write_bytes(b"GDEC-remote-work")
        vb.create_version(game, "manual-backup", "other pc progress")

        info = detect_conflict(va, vb)
        assert info["diverged"]
        assert len(info["local_only"]) == 1 and len(info["remote_only"]) == 1

        # snapshot diff shows the changed file
        d = snapshot_diff(va.zip_path(va.latest()), vb.zip_path(vb.latest()))
        assert "saves/slot_0.dat" in d["changed"], d

        # cancel does nothing
        res = sync(va, sync_dir2, decision="cancel")
        assert not res.pushed and not res.pulled

        # pull-only: only remote version arrives, marked as conflict
        res = sync(va, sync_dir2, decision="pull-only")
        assert not res.pushed and len(res.pulled) == 1 and res.conflicted
        pulled = va.latest()
        assert pulled.conflict.get("alternative", {}).get("machine")
        # the local diverging entry is marked too
        local_div = [e for e in va.entries() if e.note == "local progress"][0]
        assert local_div.conflict.get("alternative", {}).get("version")

        # merge the rest; remote side gets the local version with conflict mark
        res = sync(va, sync_dir2, decision="merge")
        assert len(res.pushed) == 1
        vb2 = VersionStore(sync_dir2)
        pushed_remote = vb2.latest()
        assert pushed_remote.conflict.get("alternative", {}).get("machine")
        # remote's own diverging entry also marked
        rem_div = [e for e in vb2.entries() if e.note == "other pc progress"][0]
        assert rem_div.conflict.get("alternative", {}).get("version")
        # nothing was deleted anywhere
        assert len(va.entries()) == 3 and len(vb2.entries()) == 3

        # second sync is a no-op (no duplicates)
        res = sync(va, sync_dir2)
        assert not res.pushed and not res.pulled

        # a version created "on top" after the merge is a clean
        # fast-forward again: the remote head IS in its ancestry
        va.create_version(game, "manual-backup", "on top")
        res = sync(va, sync_dir2)
        assert len(res.pushed) == 1 and not res.conflicted
        assert not VersionStore(sync_dir2).latest().conflict

        # a clean fast-forward (no divergence) leaves no conflict marks
        sync_dir3 = td / "sync3"
        vc = VersionStore(td / "vc")
        vc.create_version(game, "manual-backup", "a")
        vc.create_version(game, "manual-backup", "b")
        res = sync(vc, sync_dir3)
        assert len(res.pushed) == 2 and not res.conflicted
        assert not any(e.conflict for e in VersionStore(sync_dir3).entries())

        # --- settings editor ---
        gs = GameSettings(game.settings_file)
        assert gs.get("display", "fullscreen") == "false"
        apply_preset(gs, "renderer_vulkan")
        gs2 = GameSettings(game.settings_file)
        assert gs2.get("display", "renderer") == "vulkan"
        apply_preset(gs2, "windowed")
        assert GameSettings(game.settings_file).get("display", "fullscreen") == "false"

        # --- diagnostics ---
        report = analyze_log(game.latest_log())
        assert any(h.key == "render_thread_experimental" for h in report.hints)
        assert any(h.preset == "safe_render_thread" for h in report.hints)

        # --- i18n ---
        set_language("de")
        assert tr("btn.backup_now") == "Jetzt sichern"
        set_language("en")
        assert tr("btn.backup_now") == "Backup now"
        assert tr("nonexistent.key") == "nonexistent.key"

    print("ALL SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
