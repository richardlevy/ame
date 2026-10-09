"""Build new file names from tags using a pattern like ``{track:02} - {artist} - {title}``."""

from __future__ import annotations

import os
import re
import string
import uuid

from .tags import COMMON_KEYS

TOKENS = list(COMMON_KEYS["mp3"].keys())

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitise(name: str) -> str:
    name = _ILLEGAL.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name.rstrip(". ")


def _number(value: str) -> int | str:
    """'3/12' -> 3, '07' -> 7; anything non-numeric is returned unchanged."""
    head = value.split("/", 1)[0].strip()
    return int(head) if head.isdigit() else value


class _Formatter(string.Formatter):
    def __init__(self) -> None:
        super().__init__()
        self.missing: list[str] = []

    def get_value(self, key, args, kwargs):
        if isinstance(key, int) or key not in TOKENS:
            raise KeyError(f"Unknown token '{{{key}}}'. Use: {', '.join(TOKENS)}")
        value = kwargs.get(key, "")
        if value == "":
            self.missing.append(key)
        return value

    def format_field(self, value, format_spec):
        if format_spec and isinstance(value, str):
            num = _number(value)
            if isinstance(num, int):
                return format(num, format_spec)
            if value == "":
                return ""
            try:
                return format(value, format_spec)
            except ValueError:
                return value
        return format(value, format_spec)


def values_for(fmt: str, tags: dict[str, str]) -> dict[str, str]:
    out = {}
    for token, key in COMMON_KEYS[fmt].items():
        value = tags.get(key, "")
        # first value only for multi-value tags
        value = value.split(";", 1)[0].strip()
        if token == "year":
            value = value[:4]
        out[token] = value
    return out


def build_name(pattern: str, fmt: str, tags: dict[str, str], original: str) -> tuple[str, list[str]]:
    """Return (new filename incl. extension, list of tokens that had no value)."""
    formatter = _Formatter()
    stem = formatter.format(pattern, **values_for(fmt, tags))
    if formatter.missing:  # tidy separators left by empty tokens: "02 - - Title" -> "02 - Title"
        stem = re.sub(r"-(\s*-)+", "-", stem)
        stem = stem.strip(" -_.")
    stem = sanitise(stem)
    ext = os.path.splitext(original)[1]
    return (stem + ext if stem else ""), formatter.missing


def apply_renames(directory: str, pairs: list[tuple[str, str]]) -> dict[str, str | None]:
    """Rename ``old -> new`` inside ``directory``. Goes via temporary names so swaps
    and case-only changes work. Returns {old: error or None}."""
    results: dict[str, str | None] = {}
    staged: list[tuple[str, str, str]] = []
    for old, new in pairs:
        tmp = f".ame-{uuid.uuid4().hex}{os.path.splitext(old)[1]}"
        try:
            os.rename(os.path.join(directory, old), os.path.join(directory, tmp))
            staged.append((old, new, tmp))
        except OSError as e:
            results[old] = str(e)
    for old, new, tmp in staged:
        target = os.path.join(directory, new)
        try:
            if os.path.exists(target):
                raise OSError(f"'{new}' already exists")
            os.rename(os.path.join(directory, tmp), target)
            results[old] = None
        except OSError as e:
            os.rename(os.path.join(directory, tmp), os.path.join(directory, old))
            results[old] = str(e)
    return results
