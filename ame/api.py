"""The Python object exposed to the React UI as ``window.pywebview.api``.

Every public method is callable from JS and returns a Promise there.
Arguments and return values must be JSON-serialisable.
Attributes starting with ``_`` are not exposed.
"""

from __future__ import annotations

import base64
import json
import os
import traceback
from typing import Any

from . import art as ar
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

    # ------------------------------------------------------------ cover art

    def art_albums(self, directory: str, files: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Group files by album/album artist: [{id, album, artist, mbid, files: [{format, file, hasArt}]}]"""
        return ar.group_albums(directory, files)

    def art_search(self, album: str, artist: str, mbid: str = "") -> dict[str, Any]:
        """-> {candidates: [{source, title, artist, year, detail, thumb, url, original}], errors: [str]}"""
        return ar.search(album, artist, mbid)

    def art_current(self, directory: str, fmt: str, name: str) -> str | None:
        """Embedded art of one file as a small data: URL, or None."""
        return ar.art_thumbnail(fmt, os.path.join(directory, _check_name(name)))

    def art_choose_file(self) -> dict[str, Any] | None:
        """Pick a local image -> {url, thumb, width, height} or None if cancelled."""
        import webview

        open_dialog = getattr(getattr(webview, "FileDialog", None), "OPEN", None)
        if open_dialog is None:  # pywebview < 5
            open_dialog = webview.OPEN_DIALOG
        result = self._window.create_file_dialog(
            open_dialog, file_types=("Images (*.jpg;*.jpeg;*.png;*.webp)", "All files (*.*)"))
        if not result:
            return None
        path = result[0] if isinstance(result, (list, tuple)) else result
        return self.art_preview_local(path)

    def art_preview_local(self, path: str) -> dict[str, Any]:
        with open(path, "rb") as f:
            raw = f.read()
        _, _, w, h = ar.prepare_image(raw, None)
        thumb, mime, _, _ = ar.prepare_image(raw, 250)
        return {"url": "file://" + os.path.abspath(path), "width": w, "height": h,
                "thumb": f"data:{mime};base64,{base64.b64encode(thumb).decode()}"}

    def art_apply(self, directory: str, request: dict[str, Any]) -> dict[str, Any]:
        """request: {url, original?, files: [{format, file}], embed, folderFile, maxSize, replace}

        Downloads the image (falling back to ``original`` if ``url`` fails), resizes it to fit
        within maxSize x maxSize when larger (maxSize 0/None keeps the original size),
        embeds it in the files and/or writes it into the folder as ``folderFile``.
        -> {embedded, skipped, folderFile, width, height, errors: [str]}
        """
        max_size = int(request.get("maxSize") or 0) or None
        url = request["url"]
        # for "keep original size" prefer the full-size source when there is one
        urls = [request.get("original") or url, url] if not max_size else [url, request.get("original")]
        raw, last_error = None, None
        for u in [u for u in urls if u]:
            try:
                if u.startswith("file://"):
                    with open(u[len("file://"):], "rb") as f:
                        raw = f.read()
                else:
                    raw = ar.download(u)
                break
            except (ar.ArtError, OSError) as e:
                last_error = e
        if raw is None:
            raise ar.ArtError(f"Couldn't download the image: {last_error}")
        data, mime, w, h = ar.prepare_image(raw, max_size)

        result: dict[str, Any] = {"embedded": 0, "skipped": 0, "folderFile": None, "width": w, "height": h, "errors": []}
        if request.get("embed"):
            for f in request.get("files", []):
                try:
                    path = os.path.join(directory, _check_name(f["file"]))
                    if ar.embed_art(f["format"], path, data, mime, w, h, bool(request.get("replace"))):
                        result["embedded"] += 1
                    else:
                        result["skipped"] += 1
                except Exception as e:
                    traceback.print_exc()
                    result["errors"].append(f"{f['file']}: {e}")
        folder_file = (request.get("folderFile") or "").strip()
        if folder_file:
            stem = os.path.splitext(_check_name(folder_file))[0]
            name = stem + ".jpg"
            path = os.path.join(directory, name)
            if os.path.exists(path) and not request.get("replace"):
                result["errors"].append(f"{name} already exists (tick 'Replace existing art' to overwrite)")
            else:
                with open(path, "wb") as f:
                    f.write(data)
                result["folderFile"] = name
        return result

    # ------------------------------------------------------------ internals

    @staticmethod
    def _column(fmt: str, key: str) -> dict[str, str]:
        return {"key": key, "label": tg.label_for(fmt, key)}

    @staticmethod
    def _row(fmt: str, directory: str, name: str) -> dict[str, Any]:
        path = os.path.join(directory, name)
        try:
            return {"file": name, "tags": tg.read_tags(fmt, path), "length": tg.read_length(fmt, path),
                    "hasArt": ar.has_art(fmt, path)}
        except Exception as e:
            return {"file": name, "tags": {}, "length": None, "error": f"Couldn't read tags: {e}"}
