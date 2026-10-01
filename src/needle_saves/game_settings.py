"""Editor for the game's settings.cfg (Godot ConfigFile / INI format).

The file uses Godot-typed values like ``Vector2i(1280, 720)``,
``PackedStringArray(...)`` and quoted strings. We keep the raw textual
value per key so nothing is lost on round-trip; the GUI offers friendly
editors for the well-known keys only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
KV_RE = re.compile(r"^([^=]+?)\s*=\s*(.*)$")


@dataclass
class Setting:
    section: str
    key: str
    raw_value: str

    @property
    def value(self) -> str:
        """Value with Godot quoting removed (for plain scalars/strings)."""
        v = self.raw_value.strip()
        if len(v) >= 2 and v.startswith('"') and v.endswith('"'):
            return v[1:-1]
        return v


class GameSettings:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.sections: dict[str, dict[str, str]] = {}
        self._lines: list[str] = []
        self.load()

    def load(self) -> None:
        self.sections = {}
        self._lines = []
        if not self.path.is_file():
            return
        self._lines = self.path.read_text(encoding="utf-8").splitlines()
        section = ""
        for line in self._lines:
            m = SECTION_RE.match(line)
            if m:
                section = m.group(1)
                self.sections.setdefault(section, {})
                continue
            m = KV_RE.match(line)
            if m and section:
                self.sections[section][m.group(1).strip()] = m.group(2).strip()

    def get(self, section: str, key: str, default: str = "") -> str:
        raw = self.sections.get(section, {}).get(key)
        if raw is None:
            return default
        if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
            return raw[1:-1]
        return raw

    def set(self, section: str, key: str, raw_value: str) -> None:
        """Set a key, preserving file layout. raw_value is written verbatim
        (quote strings yourself, e.g. '\"vulkan\"')."""
        if section in self.sections and key in self.sections[section]:
            self._replace_line(section, key, raw_value)
        else:
            self._insert_line(section, key, raw_value)
        self.sections.setdefault(section, {})[key] = raw_value

    def _replace_line(self, section: str, key: str, raw_value: str) -> None:
        current = ""
        for i, line in enumerate(self._lines):
            m = SECTION_RE.match(line)
            if m:
                current = m.group(1)
                continue
            if current == section:
                m = KV_RE.match(line)
                if m and m.group(1).strip() == key:
                    self._lines[i] = f"{key}={raw_value}"
                    return

    def _insert_line(self, section: str, key: str, raw_value: str) -> None:
        # find end of the section block, else append a new section
        current = ""
        insert_at = len(self._lines)
        for i, line in enumerate(self._lines):
            m = SECTION_RE.match(line)
            if m:
                if current == section:
                    insert_at = i
                    break
                current = m.group(1)
            elif current == section:
                insert_at = i + 1
        if current != section:
            self._lines.extend(["", f"[{section}]", "", f"{key}={raw_value}"])
        else:
            self._lines.insert(insert_at, f"{key}={raw_value}")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(self._lines) + "\n", encoding="utf-8")

    def all_settings(self) -> list[Setting]:
        out = []
        for sec, kv in self.sections.items():
            for k, v in kv.items():
                out.append(Setting(sec, k, v))
        return out


# Keys surfaced in the GUI with friendly handling.
# (section, key, kind) - kind: bool|int|float|str|choice
KNOWN_KEYS = [
    ("display", "renderer", "choice:d3d12|vulkan|gl_compatibility|metal"),
    ("display", "fullscreen", "bool"),
    ("display", "vsync", "bool"),
    ("display", "max_fps", "int"),
    ("display", "quality", "int"),
    ("display", "render_thread", "int"),
    ("display", "menu_static", "int"),
    ("graphics", "shadows", "bool"),
    ("graphics", "wall_shadows", "bool"),
    ("graphics", "shadow_quality", "int"),
    ("graphics", "msaa", "int"),
    ("graphics", "ambient_sky", "bool"),
    ("graphics", "reflect_sky", "bool"),
    ("graphics", "reflect_probe", "bool"),
    ("graphics", "dust", "bool"),
    ("graphics", "fog", "bool"),
    ("graphics", "glow", "bool"),
    ("game", "mouse_sensitivity", "float"),
    ("game", "invert_look_x", "bool"),
    ("game", "invert_look_y", "bool"),
    ("game", "locale", "str"),
    ("save", "autosave", "bool"),
    ("save", "autosave_seconds", "float"),
    ("audio", "master", "float"),
    ("audio", "music", "float"),
    ("audio", "sfx", "float"),
    ("audio", "ambience", "float"),
]

# Stability presets, applied on demand before starting the game.
PRESETS = {
    "safe_render_thread": [("display", "render_thread", "0")],
    "renderer_vulkan": [("display", "renderer", '"vulkan"')],
    "renderer_d3d12": [("display", "renderer", '"d3d12"')],
    "renderer_gl_compat": [("display", "renderer", '"gl_compatibility"')],
    "windowed": [("display", "fullscreen", "false")],
    "low_graphics": [
        ("display", "quality", "0"),
        ("graphics", "shadows", "false"),
        ("graphics", "wall_shadows", "false"),
        ("graphics", "msaa", "0"),
        ("graphics", "dust", "false"),
        ("graphics", "fog", "false"),
        ("graphics", "glow", "false"),
        ("graphics", "reflect_sky", "false"),
        ("graphics", "reflect_probe", "false"),
        ("graphics", "ambient_sky", "false"),
    ],
    "vsync_off": [("display", "vsync", "false")],
}


def apply_preset(settings: GameSettings, preset: str) -> list[str]:
    applied = []
    for section, key, raw in PRESETS.get(preset, []):
        settings.set(section, key, raw)
        applied.append(f"{section}.{key}={raw}")
    if applied:
        settings.save()
    return applied
