"""Log scanning and help hints for common crash/start problems.

The game is a Godot build and writes logs/<name>.log files. We scan the
latest log for known trouble patterns and map them to actionable hints
(usually a settings.cfg change the Settings tab can apply).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Hint:
    key: str            # i18n key suffix
    severity: str       # "info" | "warning" | "critical"
    preset: str | None  # optional PRESETS key that helps


RULES: list[tuple[str, str, str, str | None]] = [
    # (regex, hint key, severity, preset)
    (r"separate rendering thread", "render_thread_experimental", "warning",
     "safe_render_thread"),
    (r"D3D12.*(crash|device|removed|error)|Failed to create.*D3D12",
     "d3d12_problem", "critical", "renderer_vulkan"),
    (r"Vulkan.*(error|failed)", "vulkan_problem", "warning", "renderer_d3d12"),
    (r"out of memory|OutOfMemory|OOM", "oom", "critical", "low_graphics"),
    (r"shader.*(error|failed|compile)", "shader_problem", "warning",
     "clear_shader_cache"),
    (r"ERROR:", "generic_errors", "info", None),
]


@dataclass
class LogReport:
    log_path: Path | None
    lines: int
    errors: int
    warnings: int
    hints: list[Hint]
    interesting_lines: list[str]


def analyze_log(path: Path | None) -> LogReport:
    if path is None or not path.is_file():
        return LogReport(path, 0, 0, 0, [], [])

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return LogReport(path, 0, 0, 0, [], [])

    lines = text.splitlines()
    errors = sum(1 for l in lines if "ERROR" in l or l.startswith("SCRIPT ERROR"))
    warnings = sum(1 for l in lines if "WARNING" in l)

    hints: list[Hint] = []
    seen: set[str] = set()
    for pattern, key, severity, preset in RULES:
        if key in seen:
            continue
        if re.search(pattern, text, re.IGNORECASE):
            hints.append(Hint(key, severity, preset))
            seen.add(key)

    interesting = [
        l for l in lines
        if re.search(r"WARNING|ERROR|crash|failed", l, re.IGNORECASE)
    ][:50]

    return LogReport(path, len(lines), errors, warnings, hints, interesting)
