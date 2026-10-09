"""The Python object exposed to the React UI as ``window.pywebview.api``.

Every public method is callable from JS and returns a Promise there.
Arguments and return values must be JSON-serialisable.
Attributes starting with ``_`` are not exposed.
"""

from __future__ import annotations

import json
import os
import traceback
from typing import Any

from . import rename as rn
from . import tags as tg


SETTINGS_PATH = os.path.join(os.path.expanduser("~"), ".config", "ame", "settings.json")


def _check_name(name: str) -> str:
    if not name or name != os.path.basename(name) or name in (".", ".."):
        raise tg.TagError(f"Invalid file name '{name}'")
    return name


class Api:
    def __init__(self, initial_directory: str | None = None) -> None:
        self._window = None
        self._initial = os.path.abspath(os.path.expanduser(initial_directory)) if initial_directory else None

    # ------------------------------------------------------------ settings

    def get_setting(self, key: str, default: Any = None) -> Any:
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                return json.load(f).get(key, default)
        except (OSError, ValueError):
            return default

    def set_setting(self, key: str, value: Any) -> None:
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        data[key] = value
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # ------------------------------------------------------------ directory

    def initial_directory(self) -> str | None:
        return self._initial

    def choose_directory(self) -> str | None:
        import webview

        folder = getattr(getattr(webview, "FileDialog", None), "FOLDER", None)
        if folder is None:  # pywebview < 5
            folder = webview.FOLDER_DIALOG
        result = self._window.create_file_dialog(folder)
        if not result:
            return None
        return result[0] if isinstance(result, (list, tuple)) else result

    def scan(self, directory: str) -> dict[str, Any]:
        directory = os.path.abspath(os.path.expanduser(directory))
        if not os.path.isdir(directory):
            raise tg.TagError(f"Not a directory: {directory}")

        rows: dict[str, list[dict]] = {"mp3": [], "m4a": [], "flac": []}
        unsupported: list[str] = []
        names = sorted(os.listdir(directory), key=str.lower)
        for name in names:
            if name.startswith("."):  # hidden + macOS ._ AppleDouble files
                continue
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext in tg.UNSUPPORTED_EXTENSIONS:
                unsupported.append(name)
                continue
            fmt = tg.format_for(name)
            if fmt:
                rows[fmt].append(self._row(fmt, directory, name))

        tables = []
        for fmt in ("mp3", "m4a", "flac"):
            if not rows[fmt]:
                continue
            keys: set[str] = {tg.COMMON_KEYS[fmt][name] for name in tg.ALWAYS_SHOW}
            for row in rows[fmt]:
                keys.update(row["tags"].keys())
            tables.append({
                "format": fmt,
                "label": tg.FORMAT_LABELS[fmt],
                "columns": [self._column(fmt, k) for k in tg.sort_columns(fmt, keys)],
                "suggestions": [self._column(fmt, k) for k in tg.COMMON_KEYS[fmt].values()],
                "rows": rows[fmt],
            })
        return {"directory": directory, "tables": tables, "unsupported": unsupported}

    # ------------------------------------------------------------ editing

    def normalise_key(self, fmt: str, name: str) -> dict[str, str]:
        return self._column(fmt, tg.normalise_key(fmt, name))

    def save(self, directory: str, changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """changes: [{format, file, tags: {key: value}, newName?}]

        Only changed keys need to be sent; an empty value deletes the tag.
        Returns one result per change: {file, ok, error?, row?}.
        """
        results = []
        for change in changes:
            fmt, name = change["format"], change["file"]
            try:
                _check_name(name)
                path = os.path.join(directory, name)
                tg.write_tags(fmt, path, change.get("tags") or {})
                new_name = (change.get("newName") or "").strip()
                if new_name and new_name != name:
                    _check_name(new_name)
                    if os.path.splitext(new_name)[1].lower() != os.path.splitext(name)[1].lower():
                        raise tg.TagError(f"Keep the {os.path.splitext(name)[1]} extension when renaming")
                    errors = rn.apply_renames(directory, [(name, new_name)])
                    if errors[name]:
                        raise tg.TagError(f"Tags saved, but rename failed: {errors[name]}")
                    name = new_name
                results.append({"file": change["file"], "ok": True, "row": self._row(fmt, directory, name)})
            except Exception as e:  # report per file, keep going
                traceback.print_exc()
                results.append({"file": change["file"], "ok": False, "error": str(e)})
        return results

    # ------------------------------------------------------------ renaming

    def rename_tokens(self) -> list[str]:
        return rn.TOKENS

    def preview_rename(self, directory: str, pattern: str, files: list[dict[str, str]]) -> list[dict[str, Any]]:
        """files: [{format, file}] -> [{file, newName, status, message}]

        status: ok | same | missing (some tokens empty, still renamable) | conflict | error
        """
        previews = []
        for f in files:
            fmt, name = f["format"], f["file"]
            try:
                tags = tg.read_tags(fmt, os.path.join(directory, _check_name(name)))
                new, missing = rn.build_name(pattern, fmt, tags, name)
                if not new:
                    previews.append({"file": name, "newName": "", "status": "error", "message": "Pattern produced an empty name"})
                elif new == name:
                    previews.append({"file": name, "newName": new, "status": "same", "message": ""})
                else:
                    status = "missing" if missing else "ok"
                    msg = f"No value for: {', '.join(sorted(set(missing)))}" if missing else ""
                    previews.append({"file": name, "newName": new, "status": status, "message": msg})
            except Exception as e:
                previews.append({"file": name, "newName": "", "status": "error", "message": str(e)})

        # conflicts: two files mapping to the same name, or onto a file that isn't moving
        moving = {p["file"].lower() for p in previews if p["status"] in ("ok", "missing")}
        existing = {n.lower() for n in os.listdir(directory)}
        seen: dict[str, int] = {}
        for p in previews:
            if p["status"] in ("ok", "missing"):
                seen[p["newName"].lower()] = seen.get(p["newName"].lower(), 0) + 1
        for p in previews:
            if p["status"] not in ("ok", "missing"):
                continue
            target = p["newName"].lower()
            if seen[target] > 1:
                p["status"], p["message"] = "conflict", "Another file would get the same name"
            elif target in existing and target not in moving and target != p["file"].lower():
                p["status"], p["message"] = "conflict", "A file with this name already exists"
        return previews

    def apply_rename(self, directory: str, pairs: list[dict[str, str]]) -> list[dict[str, Any]]:
        """pairs: [{file, newName}] -> [{file, newName, ok, error?}]"""
        clean = [(_check_name(p["file"]), _check_name(p["newName"])) for p in pairs]
        errors = rn.apply_renames(directory, clean)
        return [{"file": old, "newName": new, "ok": errors[old] is None, "error": errors[old]} for old, new in clean]

    # ------------------------------------------------------------ internals

    @staticmethod
    def _column(fmt: str, key: str) -> dict[str, str]:
        return {"key": key, "label": tg.label_for(fmt, key)}

    @staticmethod
    def _row(fmt: str, directory: str, name: str) -> dict[str, Any]:
        path = os.path.join(directory, name)
        try:
            return {"file": name, "tags": tg.read_tags(fmt, path), "length": tg.read_length(fmt, path)}
        except Exception as e:
            return {"file": name, "tags": {}, "length": None, "error": f"Couldn't read tags: {e}"}
