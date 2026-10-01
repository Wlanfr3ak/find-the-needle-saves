"""Main window - PySide6 GUI for the save manager."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__
from ..config import Config
from ..diagnostics import analyze_log
from ..game import GameData, default_game_data_dir
from ..game_settings import KNOWN_KEYS, PRESETS, GameSettings, apply_preset
from ..i18n import available_languages, set_language, tr
from ..store import VersionStore, machine_id, snapshot_diff
from ..sync import detect_conflict, remote_status, sync
from ..watcher import AutoBackuper


def open_in_explorer(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 - local file manager only
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class MainWindow(QMainWindow):
    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        set_language(config.get("language", "en"))

        self.game = self._resolve_game()
        self.store = self._resolve_store()
        self.backuper = AutoBackuper(
            self.game, self.store,
            enabled=bool(config.get("auto_backup", True)))

        self.setWindowTitle(f"{APP_NAME}  ·  app v{__version__}")
        self.resize(980, 720)

        self._build_ui()
        self._start_watcher()
        self.refresh_all()

        if self.config.get("auto_sync_on_start") and self._sync_dir():
            QTimer.singleShot(800, self.do_sync)

    # ---------- resolution helpers ----------

    def _resolve_game(self) -> GameData:
        configured = self.config.get("game_data_dir", "")
        if configured:
            return GameData(Path(configured))
        auto = default_game_data_dir()
        return GameData(auto) if auto else GameData(Path(""))

    def _default_vault(self) -> Path:
        from ..config import config_dir
        return config_dir() / "vault"

    def _resolve_store(self) -> VersionStore:
        configured = self.config.get("vault_dir", "")
        root = Path(configured) if configured else self._default_vault()
        return VersionStore(root)

    def _sync_dir(self) -> Path | None:
        d = self.config.get("sync_dir", "")
        return Path(d) if d else None

    # ---------- UI construction ----------

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)

        header = QHBoxLayout()
        self.version_label = QLabel()
        f = self.version_label.font()
        f.setPointSize(20)
        f.setBold(True)
        self.version_label.setFont(f)
        header.addWidget(self.version_label, 1)
        self.machine_label = QLabel(machine_id())
        header.addWidget(self.machine_label)
        root.addLayout(header)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        self._build_saves_tab()
        self._build_settings_tab()
        self._build_logs_tab()
        self._build_options_tab()

        self.status_label = QLabel()
        root.addWidget(self.status_label)
        self.setCentralWidget(central)

    # ----- tab: saves -----

    def _build_saves_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)

        row = QHBoxLayout()
        self.note_edit = QLineEdit()
        self.note_edit.setPlaceholderText(tr("label.note"))
        row.addWidget(self.note_edit, 1)
        for key, handler in [
            ("btn.backup_now", self.do_backup),
            ("btn.restore", self.do_restore),
            ("btn.sync_now", self.do_sync),
            ("btn.refresh", self.refresh_all),
            ("btn.open_game_dir", lambda: open_in_explorer(self.game.root)),
            ("btn.open_vault", lambda: open_in_explorer(self.store.root)),
        ]:
            b = QPushButton(tr(key))
            b.clicked.connect(handler)
            row.addWidget(b)
        lay.addLayout(row)

        self.versions_table = QTableWidget(0, 5)
        self.versions_table.setHorizontalHeaderLabels([
            tr("col.version"), tr("col.date"), tr("col.action"),
            tr("col.machine"), tr("col.note"),
        ])
        self.versions_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.versions_table.setSelectionMode(QTableWidget.SingleSelection)
        self.versions_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.versions_table.horizontalHeader().setStretchLastSection(True)
        versions_group = QGroupBox(tr("group.versions"))
        vg = QVBoxLayout(versions_group)
        vg.addWidget(self.versions_table)
        lay.addWidget(versions_group, 2)

        changelog_group = QGroupBox(tr("group.changelog"))
        cg = QVBoxLayout(changelog_group)
        self.changelog_view = QPlainTextEdit()
        self.changelog_view.setReadOnly(True)
        cg.addWidget(self.changelog_view)
        lay.addWidget(changelog_group, 1)

        self.tabs.addTab(w, tr("tab.saves"))

    # ----- tab: settings -----

    def _build_settings_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)

        presets_group = QGroupBox(tr("group.presets"))
        pg = QHBoxLayout(presets_group)
        self.preset_buttons = {}
        for preset in PRESETS:
            b = QPushButton(tr(f"preset.{preset}"))
            b.clicked.connect(lambda _=False, p=preset: self.apply_preset(p))
            pg.addWidget(b)
            self.preset_buttons[preset] = b
        pg.addStretch(1)
        lay.addWidget(presets_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        form = QFormLayout(inner)
        self.setting_widgets: dict[tuple[str, str], QWidget] = {}
        for section, key, kind in KNOWN_KEYS:
            label = QLabel(f"{section}.{key}")
            if kind == "bool":
                widget = QCheckBox()
            elif kind.startswith("choice:"):
                widget = QComboBox()
                widget.addItems(kind.split(":", 1)[1].split("|"))
                widget.setEditable(True)
            elif kind == "int":
                widget = QSpinBox()
                widget.setRange(-1, 1_000_000)
            else:
                widget = QLineEdit()
            self.setting_widgets[(section, key)] = widget
            form.addRow(label, widget)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        save_btn = QPushButton(tr("btn.save_settings"))
        save_btn.clicked.connect(self.save_settings)
        lay.addWidget(save_btn)
        self.tabs.addTab(w, tr("tab.settings"))

    # ----- tab: logs -----

    def _build_logs_tab(self) -> None:
        w = QWidget()
        lay = QVBoxLayout(w)

        row = QHBoxLayout()
        self.logs_list = QListWidget()
        self.logs_list.currentItemChanged.connect(self._show_log)
        row.addWidget(self.logs_list, 1)

        right = QVBoxLayout()
        hints_group = QGroupBox(tr("label.hints"))
        hg = QVBoxLayout(hints_group)
        self.hints_list = QListWidget()
        hg.addWidget(self.hints_list)
        right.addWidget(hints_group)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        right.addWidget(self.log_view, 1)
        row.addLayout(right, 3)
        lay.addLayout(row, 1)

        btns = QHBoxLayout()
        for key, handler in [
            ("btn.open_log_dir", lambda: open_in_explorer(self.game.logs_dir)),
            ("btn.clear_shader_cache", self.clear_shader_cache),
            ("btn.refresh", self.refresh_all),
        ]:
            b = QPushButton(tr(key))
            b.clicked.connect(handler)
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)
        self.tabs.addTab(w, tr("tab.logs"))

    # ----- tab: options -----

    def _build_options_tab(self) -> None:
        w = QWidget()
        lay = QFormLayout(w)

        self.opt_game_dir = self._add_path_row(lay, "label.game_dir")
        self.opt_vault_dir = self._add_path_row(lay, "label.vault_dir")
        self.opt_sync_dir = self._add_path_row(lay, "label.sync_dir")

        self.opt_language = QComboBox()
        self.opt_language.addItems(available_languages())
        lay.addRow(tr("label.language"), self.opt_language)

        self.opt_auto_backup = QCheckBox()
        lay.addRow(tr("label.auto_backup"), self.opt_auto_backup)
        self.opt_interval = QSpinBox()
        self.opt_interval.setRange(5, 3600)
        lay.addRow(tr("label.auto_backup_interval"), self.opt_interval)
        self.opt_auto_sync = QCheckBox()
        lay.addRow(tr("label.auto_sync"), self.opt_auto_sync)
        self.opt_include_logs = QCheckBox()
        lay.addRow(tr("label.include_logs"), self.opt_include_logs)
        self.opt_restore_settings = QCheckBox()
        lay.addRow(tr("label.include_settings_default"), self.opt_restore_settings)
        self.opt_redact = QCheckBox()
        lay.addRow(tr("label.redact_identity"), self.opt_redact)

        save_btn = QPushButton(tr("btn.save_settings"))
        save_btn.clicked.connect(self.save_options)
        lay.addRow(save_btn)
        lay.addRow(QLabel(tr("app.version", version=__version__)))
        self.tabs.addTab(w, tr("tab.options"))

    def _add_path_row(self, lay: QFormLayout, label_key: str) -> QLineEdit:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit()
        b = QPushButton(tr("btn.browse"))
        b.clicked.connect(lambda: self._browse(edit))
        h.addWidget(edit, 1)
        h.addWidget(b)
        lay.addRow(tr(label_key), row)
        return edit

    def _browse(self, edit: QLineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, APP_NAME, edit.text() or str(Path.home()))
        if d:
            edit.setText(d)

    # ---------- refresh ----------

    def refresh_all(self) -> None:
        # options reflect current config
        if hasattr(self, "opt_game_dir"):
            self.opt_game_dir.setText(str(self.game.root))
            self.opt_vault_dir.setText(str(self.store.root))
            self.opt_sync_dir.setText(self.config.get("sync_dir", ""))
            self.opt_language.setCurrentText(self.config.get("language", "en"))
            self.opt_auto_backup.setChecked(bool(self.config.get("auto_backup", True)))
            self.opt_interval.setValue(int(self.config.get("auto_backup_interval_seconds", 20)))
            self.opt_auto_sync.setChecked(bool(self.config.get("auto_sync_on_start")))
            self.opt_include_logs.setChecked(bool(self.config.get("include_logs_in_snapshots")))
            self.opt_restore_settings.setChecked(bool(self.config.get("restore_include_settings", False)))
            self.opt_redact.setChecked(bool(self.config.get("redact_identity_tokens_in_sync", True)))

        self._refresh_versions()
        self._refresh_settings_form()
        self._refresh_logs()
        self._refresh_status()

    def _refresh_versions(self) -> None:
        entries = self.store.entries()
        latest = self.store.latest()
        self.version_label.setText(
            f"{tr('save.version')}: v{latest.version}" if latest
            else f"{tr('save.version')}: {tr('save.version.none')}"
        )
        self.versions_table.setRowCount(len(entries))
        for row, e in enumerate(reversed(entries)):
            origin = ""
            if e.origin:
                origin = f" ← {e.origin.get('machine','?')} v{e.origin.get('version','?')}"
            conflict = f" [{tr('label.conflict')}]" if e.conflict else ""
            for col, text in enumerate([
                f"v{e.version}", e.created_at, e.action + origin + conflict,
                e.machine, e.note,
            ]):
                self.versions_table.setItem(row, col, QTableWidgetItem(text))
        self.versions_table.resizeColumnsToContents()

        changelog = self.store.root / "CHANGELOG.md"
        if changelog.is_file():
            self.changelog_view.setPlainText(changelog.read_text(encoding="utf-8"))
        else:
            self.changelog_view.setPlainText("")

    def _refresh_settings_form(self) -> None:
        if not self.game.settings_file.is_file():
            return
        settings = GameSettings(self.game.settings_file)
        for (section, key), widget in self.setting_widgets.items():
            raw = settings.sections.get(section, {}).get(key)
            if raw is None:
                continue
            value = settings.get(section, key)
            if isinstance(widget, QCheckBox):
                widget.setChecked(raw.lower() == "true")
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(value)
            elif isinstance(widget, QSpinBox):
                try:
                    widget.setValue(int(float(raw)))
                except ValueError:
                    pass
            elif isinstance(widget, QLineEdit):
                widget.setText(value)

    def _refresh_logs(self) -> None:
        self.logs_list.clear()
        latest = self.game.latest_log()
        for p in self.game.all_logs():
            item = QListWidgetItem(p.name + ("  (latest)" if p == latest else ""))
            item.setData(Qt.UserRole, p)
            self.logs_list.addItem(item)
        if latest:
            self.logs_list.setCurrentRow(self.logs_list.count() - 1)
            self._show_log(self.logs_list.currentItem())
        else:
            self.log_view.setPlainText("")
            self.hints_list.clear()

    def _show_log(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        path: Path = item.data(Qt.UserRole)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.log_view.setPlainText(str(exc))
            return
        self.log_view.setPlainText(text)

        report = analyze_log(path)
        self.hints_list.clear()
        if report.hints:
            for hint in report.hints:
                QListWidgetItem(tr(f"hint.{hint.key}"), self.hints_list)
        else:
            QListWidgetItem(tr("hint.no_hints"), self.hints_list)

    def _refresh_status(self) -> None:
        parts = [f"{tr('label.status')}:"]
        if not self.game.exists:
            parts.append(tr("msg.game_dir_missing"))
        sd = self._sync_dir()
        if sd:
            st = remote_status(self.store, sd)
            if st["available"]:
                parts.append(tr(
                    "label.latest_remote",
                    version=st.get("remote_latest", 0),
                    local_only=st["local_only"],
                    remote_only=st["remote_only"],
                ))
            else:
                parts.append(tr("label.remote_missing"))
        self.status_label.setText("  ".join(parts))

    # ---------- actions ----------

    def do_backup(self) -> None:
        if not self.game.exists:
            self._err(tr("msg.game_dir_missing"))
            return
        entry = self.store.create_version(
            self.game, "manual-backup", self.note_edit.text().strip())
        self.note_edit.clear()
        self._info(tr("msg.backup_done", version=entry.version))
        self.refresh_all()

    def do_restore(self) -> None:
        row = self.versions_table.currentRow()
        if row < 0:
            self._err(tr("msg.no_version_selected"))
            return
        version_text = self.versions_table.item(row, 0).text()
        version = int(version_text.lstrip("v"))
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(tr("msg.restore_confirm", version=version))
        settings_cb = QCheckBox(tr("label.restore_include_settings"))
        settings_cb.setChecked(
            bool(self.config.get("restore_include_settings", False)))
        box.setCheckBox(settings_cb)
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        if box.exec() != QMessageBox.Yes:
            return
        try:
            safety = self.store.restore(
                version, self.game,
                include_settings=settings_cb.isChecked())
            self._info(tr("msg.restore_done", version=version, safety=safety.version))
        except (OSError, ValueError) as exc:
            self._err(tr("msg.error", error=exc))
        self.refresh_all()
        self.backuper.mark_clean()

    def do_sync(self) -> None:
        sd = self._sync_dir()
        if sd is None:
            self._err(tr("label.remote_missing"))
            return
        sd.mkdir(parents=True, exist_ok=True)
        remote = VersionStore(sd)
        info = detect_conflict(self.store, remote)
        decision = "merge"
        if info["diverged"]:
            choice = self._ask_conflict(info, remote)
            if choice is None:
                return
            decision = choice
        result = sync(self.store, sd, decision=decision)
        if result.errors:
            self._err(tr("msg.sync_errors", errors="\n".join(result.errors)))
        else:
            self._info(tr("msg.sync_done",
                         pushed=len(result.pushed), pulled=len(result.pulled)))
        self.refresh_all()

    def _ask_conflict(self, info: dict, remote: VersionStore) -> str | None:
        """Diverged vaults: show the diff and ask what to do.

        Returns 'merge' | 'pull-only' | 'push-only' | None (cancel).
        """
        lines = [tr("conflict.detected"), ""]
        lines.append(tr("conflict.local_new"))
        for e in info["local_only"]:
            lines.append(f"  v{e.version} · {e.created_at} · {e.action} · {e.note}")
        lines.append(tr("conflict.remote_new"))
        for e in info["remote_only"]:
            lines.append(f"  v{e.version} · {e.created_at} · {e.action} · {e.note}")

        ll, rl = info["local_latest"], info["remote_latest"]
        if ll and rl:
            try:
                diff = snapshot_diff(self.store.zip_path(ll), remote.zip_path(rl))
                details = []
                if diff["changed"]:
                    details.append(tr("conflict.files_changed",
                                      files=", ".join(diff["changed"])))
                if diff["added"]:
                    details.append(tr("conflict.files_added",
                                      files=", ".join(diff["added"])))
                if diff["removed"]:
                    details.append(tr("conflict.files_removed",
                                      files=", ".join(diff["removed"])))
                if not details:
                    details.append(tr("conflict.files_same"))
                lines += ["", tr("conflict.diff_header")] + [
                    f"  {d}" for d in details]
            except OSError:
                pass

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle(APP_NAME)
        box.setText("\n".join(lines))
        merge_btn = box.addButton(tr("conflict.merge"), QMessageBox.AcceptRole)
        pull_btn = box.addButton(tr("conflict.pull"), QMessageBox.ActionRole)
        push_btn = box.addButton(tr("conflict.push"), QMessageBox.ActionRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(merge_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked is merge_btn:
            return "merge"
        if clicked is pull_btn:
            return "pull-only"
        if clicked is push_btn:
            return "push-only"
        return None

    def save_settings(self) -> None:
        if not self.game.exists:
            self._err(tr("msg.game_dir_missing"))
            return
        backup = self.store.create_version(self.game, "settings-change",
                                           "backup before settings change")
        settings = GameSettings(self.game.settings_file)
        for (section, key), widget in self.setting_widgets.items():
            if isinstance(widget, QCheckBox):
                raw = "true" if widget.isChecked() else "false"
            elif isinstance(widget, QComboBox):
                raw = f'"{widget.currentText()}"'
            elif isinstance(widget, QSpinBox):
                raw = str(widget.value())
            else:
                text = widget.text()
                raw = text if self._looks_typed(text) else f'"{text}"'
            settings.set(section, key, raw)
        settings.save()
        self._info(tr("msg.settings_saved", version=backup.version))
        self.refresh_all()

    @staticmethod
    def _looks_typed(text: str) -> bool:
        t = text.strip()
        if t in ("true", "false"):
            return True
        try:
            float(t)
            return True
        except ValueError:
            return False

    def apply_preset(self, preset: str) -> None:
        if not self.game.exists:
            self._err(tr("msg.game_dir_missing"))
            return
        backup = self.store.create_version(self.game, "settings-change",
                                           f"backup before preset {preset}")
        settings = GameSettings(self.game.settings_file)
        changes = apply_preset(settings, preset)
        self._info(tr("msg.preset_applied", preset=tr(f"preset.{preset}"),
                      changes="\n".join(changes), version=backup.version))
        self.refresh_all()

    def clear_shader_cache(self) -> None:
        removed = self.game.clear_shader_cache()
        self._info(tr("msg.shader_cache_cleared", count=removed))
        self.refresh_all()

    def save_options(self) -> None:
        self.config.set("game_data_dir", self.opt_game_dir.text().strip())
        self.config.set("vault_dir", self.opt_vault_dir.text().strip())
        self.config.set("sync_dir", self.opt_sync_dir.text().strip())
        self.config.set("language", self.opt_language.currentText())
        self.config.set("auto_backup", self.opt_auto_backup.isChecked())
        self.config.set("auto_backup_interval_seconds", self.opt_interval.value())
        self.config.set("auto_sync_on_start", self.opt_auto_sync.isChecked())
        self.config.set("include_logs_in_snapshots", self.opt_include_logs.isChecked())
        self.config.set("restore_include_settings", self.opt_restore_settings.isChecked())
        self.config.set("redact_identity_tokens_in_sync", self.opt_redact.isChecked())

        self.game = self._resolve_game()
        self.store = self._resolve_store()
        self.backuper = AutoBackuper(
            self.game, self.store,
            enabled=bool(self.config.get("auto_backup", True)))
        self._start_watcher()
        self.refresh_all()

    # ---------- auto backup watcher ----------

    def _start_watcher(self) -> None:
        if hasattr(self, "_watcher"):
            self._watcher.stop()
        self._watcher = QTimer(self)
        interval = max(5, int(self.config.get("auto_backup_interval_seconds", 20)))
        self._watcher.setInterval(interval * 1000)
        self._watcher.timeout.connect(self._watcher_tick)
        if self.config.get("auto_backup", True):
            self._watcher.start()

    def _watcher_tick(self) -> None:
        self.backuper.enabled = bool(self.config.get("auto_backup", True))
        try:
            entry = self.backuper.tick()
        except OSError:
            return
        if entry is not None:
            self.refresh_all()

    # ---------- helpers ----------

    def _info(self, text: str) -> None:
        self.status_label.setText(text)
        self.statusBar().showMessage(text, 8000)

    def _err(self, text: str) -> None:
        QMessageBox.warning(self, APP_NAME, text)
