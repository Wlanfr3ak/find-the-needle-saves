"""Minimal JSON-file based i18n.

Locale files live in <package>/locales/<lang>.json and are flat
key -> string maps. Missing keys fall back to English, then to the key
itself. New languages are added by dropping in another JSON file.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_LOCALE_DIR = Path(__file__).resolve().parent / "locales"
_current_lang = "en"


def available_languages() -> list[str]:
    if not _LOCALE_DIR.is_dir():
        return ["en"]
    return sorted(p.stem for p in _LOCALE_DIR.glob("*.json")) or ["en"]


@lru_cache(maxsize=8)
def _load(lang: str) -> dict[str, str]:
    path = _LOCALE_DIR / f"{lang}.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def set_language(lang: str) -> None:
    global _current_lang
    _current_lang = lang


def language() -> str:
    return _current_lang


def tr(key: str, **kwargs) -> str:
    text = _load(_current_lang).get(key) or _load("en").get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
