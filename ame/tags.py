"""Reading and writing tags for mp3 (ID3), m4a (MP4 atoms) and flac (Vorbis comments).

Every tag is exposed as a flat ``key -> str`` mapping so the UI can treat all
formats the same way. Multi-value tags are joined with ``SEP`` on read and
split again on write. An empty string on write deletes the tag.

Keys are the format's native identifiers:
  mp3   ID3 HashKeys, e.g. ``TIT2``, ``TXXX:MusicBrainz Album Id``, ``COMM:desc:eng``
  m4a   atom names, e.g. ``\xa9nam``, ``trkn``, ``----:com.apple.iTunes:ISRC``
  flac  upper-cased Vorbis field names, e.g. ``TITLE``, ``TRACKNUMBER``
"""

from __future__ import annotations

import os
from typing import Any

from mutagen.flac import FLAC
from mutagen.id3 import (
    COMM,
    ID3,
    TXXX,
    USLT,
    WXXX,
    Frames,
    ID3NoHeaderError,
    TextFrame,
    UrlFrame,
)
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4FreeForm

SEP = "; "

# extension -> format id
EXTENSIONS = {
    ".mp3": "mp3",
    ".m4a": "m4a",
    ".m4b": "m4a",
    ".mp4": "m4a",
    ".flac": "flac",
}
# Raw ADTS .aac has no real tag container, so we list these but don't edit them.
UNSUPPORTED_EXTENSIONS = {".aac"}

FORMAT_LABELS = {"mp3": "MP3", "m4a": "AAC / M4A", "flac": "FLAC"}

# Common names used by the rename pattern and the "add column" box.
COMMON_KEYS: dict[str, dict[str, str]] = {
    "mp3": {
        "title": "TIT2", "artist": "TPE1", "albumartist": "TPE2", "album": "TALB",
        "track": "TRCK", "disc": "TPOS", "year": "TDRC", "genre": "TCON",
        "composer": "TCOM", "comment": "COMM::eng", "grouping": "TIT1", "bpm": "TBPM",
        "compilation": "TCMP", "lyrics": "USLT::eng",
    },
    "m4a": {
        "title": "\xa9nam", "artist": "\xa9ART", "albumartist": "aART", "album": "\xa9alb",
        "track": "trkn", "disc": "disk", "year": "\xa9day", "genre": "\xa9gen",
        "composer": "\xa9wrt", "comment": "\xa9cmt", "grouping": "\xa9grp", "bpm": "tmpo",
        "compilation": "cpil", "lyrics": "\xa9lyr",
    },
    "flac": {
        "title": "TITLE", "artist": "ARTIST", "albumartist": "ALBUMARTIST", "album": "ALBUM",
        "track": "TRACKNUMBER", "disc": "DISCNUMBER", "year": "DATE", "genre": "GENRE",
        "composer": "COMPOSER", "comment": "COMMENT", "grouping": "GROUPING", "bpm": "BPM",
        "compilation": "COMPILATION", "lyrics": "LYRICS",
    },
}

# Columns shown in every table even when no file in the folder has the tag.
# Names are keys of COMMON_KEYS, e.g. add "track" or "albumartist".
ALWAYS_SHOW = ["disc"]

# Column order: these come first (in this order), everything else alphabetically.
_COMMON_ORDER = ["title", "artist", "album", "albumartist", "track", "disc", "year", "genre",
                 "composer", "comment"]

_LABELS = {
    "mp3": {
        "TIT2": "Title", "TPE1": "Artist", "TPE2": "Album Artist", "TALB": "Album",
        "TRCK": "Track", "TPOS": "Disc", "TDRC": "Date", "TCON": "Genre", "TCOM": "Composer",
        "TBPM": "BPM", "TCMP": "Compilation", "TIT1": "Grouping", "TIT3": "Subtitle",
        "TSOP": "Artist Sort", "TSO2": "Album Artist Sort", "TSOA": "Album Sort",
        "TSOT": "Title Sort", "TSOC": "Composer Sort", "TPUB": "Publisher",
        "TCOP": "Copyright", "TENC": "Encoded By", "TSSE": "Encoder Settings",
        "TLAN": "Language", "TKEY": "Key", "TOPE": "Original Artist", "TDOR": "Original Date",
        "TMED": "Media", "TSRC": "ISRC", "TEXT": "Lyricist", "TPE3": "Conductor",
        "TPE4": "Remixer", "TLEN": "Length (ms)", "TDRL": "Release Date", "TMOO": "Mood",
        "TOAL": "Original Album", "TFLT": "File Type", "TOWN": "Owner", "TDEN": "Encoding Time",
        "TDTG": "Tagging Time", "TSST": "Set Subtitle",
    },
    "m4a": {
        "\xa9nam": "Title", "\xa9ART": "Artist", "aART": "Album Artist", "\xa9alb": "Album",
        "trkn": "Track", "disk": "Disc", "\xa9day": "Year", "\xa9gen": "Genre",
        "\xa9wrt": "Composer", "\xa9cmt": "Comment", "\xa9grp": "Grouping", "\xa9lyr": "Lyrics",
        "\xa9too": "Encoder", "cpil": "Compilation", "tmpo": "BPM", "cprt": "Copyright",
        "soar": "Artist Sort", "soaa": "Album Artist Sort", "sonm": "Title Sort",
        "soal": "Album Sort", "soco": "Composer Sort", "desc": "Description",
        "pgap": "Gapless", "stik": "Media Kind", "rtng": "Rating", "\xa9wrk": "Work",
        "\xa9mvn": "Movement", "\xa9mvi": "Movement No.", "\xa9mvc": "Movement Count",
        "shwm": "Show Movement", "purd": "Purchase Date", "apID": "Apple ID",
    },
    "flac": {
        "ALBUMARTIST": "Album Artist", "TRACKNUMBER": "Track", "TRACKTOTAL": "Track Total",
        "TOTALTRACKS": "Track Total", "DISCNUMBER": "Disc", "DISCTOTAL": "Disc Total",
        "TOTALDISCS": "Disc Total", "DATE": "Date", "ORIGINALDATE": "Original Date",
        "ALBUMARTISTSORT": "Album Artist Sort", "ARTISTSORT": "Artist Sort",
        "ALBUMSORT": "Album Sort", "TITLESORT": "Title Sort", "ISRC": "ISRC", "BPM": "BPM",
    },
}

# MP4 atoms whose values are integers / booleans rather than text.
_MP4_INT_KEYS = {
    "tmpo", "\xa9mvi", "\xa9mvc", "tvsn", "tves", "cnID", "sfID", "atID", "geID",
    "cmID", "plID", "akID", "stik", "rtng", "hdvd", "shwm",
}
_MP4_BOOL_KEYS = {"cpil", "pgap", "pcst"}
_MP4_SKIP = {"covr"}  # artwork: binary, not shown in the table
_MP4_FREEFORM_PREFIX = "----:com.apple.iTunes:"


class TagError(Exception):
    pass


# ---------------------------------------------------------------- helpers

def _join(values: Any) -> str:
    return SEP.join(str(v) for v in values)


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(SEP.strip()) if v.strip()]


def label_for(fmt: str, key: str) -> str:
    """Human-friendly column header for a native tag key."""
    known = _LABELS.get(fmt, {}).get(key)
    if known:
        return known
    if fmt == "mp3":
        fid, _, rest = key.partition(":")
        if fid == "TXXX":
            return rest or "TXXX"
        if fid in ("COMM", "USLT"):
            desc, _, lang = rest.partition(":")
            base = "Comment" if fid == "COMM" else "Lyrics"
            return f"{base} ({desc})" if desc else base
        if fid == "WXXX":
            return f"URL ({rest})" if rest else "URL"
        return key
    if fmt == "m4a":
        if key.startswith("----:"):
            return key.rsplit(":", 1)[-1]
        return key.replace("\xa9", "©")
    if fmt == "flac":
        return key.replace("_", " ").title()
    return key


def sort_columns(fmt: str, keys: set[str]) -> list[str]:
    common = COMMON_KEYS[fmt]
    first = [common[name] for name in _COMMON_ORDER if common[name] in keys]
    rest = sorted((k for k in keys if k not in first), key=lambda k: label_for(fmt, k).lower())
    return first + rest


def normalise_key(fmt: str, name: str) -> str:
    """Turn what the user typed in "add column" into a native key for ``fmt``."""
    name = name.strip()
    if not name:
        raise TagError("Tag name is empty")
    common = COMMON_KEYS[fmt].get(name.lower().replace(" ", "").replace("_", ""))
    if common:
        return common
    if fmt == "mp3":
        fid, _, rest = name.partition(":")
        if fid.upper() in ("COMM", "USLT"):
            desc, _, lang = rest.partition(":")
            return f"{fid.upper()}:{desc}:{(lang or 'eng')[:3]}"
        if fid.upper() in ("TXXX", "WXXX"):
            return f"{fid.upper()}:{rest}"
        if len(name) == 4 and name.upper() in Frames:
            return name.upper()
        return f"TXXX:{name}"
    if fmt == "m4a":
        if name.startswith("----:") or name in _LABELS["m4a"] or name.replace("©", "\xa9") in _LABELS["m4a"]:
            return name.replace("©", "\xa9")
        return _MP4_FREEFORM_PREFIX + name
    if fmt == "flac":
        if "=" in name or any(ord(c) < 0x20 or ord(c) > 0x7D for c in name):
            raise TagError("FLAC tag names must be plain ASCII without '='")
        return name.upper()
    raise TagError(f"Unknown format {fmt}")


# ---------------------------------------------------------------- mp3

def _read_mp3(path: str) -> dict[str, str]:
    try:
        id3 = ID3(path)
    except ID3NoHeaderError:
        return {}
    out: dict[str, str] = {}
    for key, frame in id3.items():
        if isinstance(frame, (TextFrame,)) and not isinstance(frame, (COMM, USLT)):
            out[key] = _join(frame.text)
        elif isinstance(frame, COMM):
            out[key] = _join(frame.text)
        elif isinstance(frame, USLT):
            out[key] = frame.text
        elif isinstance(frame, (UrlFrame, WXXX)):
            out[key] = frame.url
        # APIC (art), PRIV, GEOB, UFID, etc. are binary and skipped.
    return out


def _mp3_frame(key: str, value: str):
    fid, _, rest = key.partition(":")
    if fid == "TXXX":
        return TXXX(encoding=3, desc=rest, text=_split(value))
    if fid in ("COMM", "USLT"):
        desc, _, lang = rest.partition(":")
        lang = (lang or "eng")[:3]
        if fid == "COMM":
            return COMM(encoding=3, desc=desc, lang=lang, text=_split(value))
        return USLT(encoding=3, desc=desc, lang=lang, text=value)
    if fid == "WXXX":
        return WXXX(encoding=3, desc=rest, url=value)
    cls = Frames.get(fid)
    if cls is None:
        raise TagError(f"Unknown ID3 frame '{fid}'")
    if issubclass(cls, UrlFrame):
        return cls(url=value)
    if issubclass(cls, TextFrame):
        return cls(encoding=3, text=_split(value))
    raise TagError(f"ID3 frame '{fid}' can't be edited as text")


def _write_mp3(path: str, changes: dict[str, str]) -> None:
    try:
        id3 = ID3(path)
    except ID3NoHeaderError:
        id3 = ID3()
    for key, value in changes.items():
        if key in id3:
            del id3[key]
        if value.strip():
            frame = _mp3_frame(key, value)
            id3.add(frame)
    version = 3 if id3.version and id3.version[1] == 3 else 4
    id3.save(path, v2_version=version)


# ---------------------------------------------------------------- m4a

def _mp4_value_to_str(key: str, val: Any) -> str | None:
    if key in _MP4_SKIP:
        return None
    if key in ("trkn", "disk"):
        num, total = val[0]
        return f"{num}/{total}" if total else str(num)
    if isinstance(val, bool):
        return "1" if val else "0"
    if key.startswith("----"):
        return _join(bytes(v).decode("utf-8", "replace") for v in val)
    if isinstance(val, list):
        if val and isinstance(val[0], (bytes, bytearray)):
            return None
        return _join(val)
    return str(val)


def _parse_pair(value: str) -> list[tuple[int, int]]:
    num, _, total = value.partition("/")
    try:
        return [(int(num.strip() or 0), int(total.strip() or 0))]
    except ValueError:
        raise TagError(f"Expected 'n' or 'n/total', got '{value}'") from None


def _read_m4a(path: str) -> dict[str, str]:
    tags = MP4(path).tags or {}
    out: dict[str, str] = {}
    for key, val in tags.items():
        s = _mp4_value_to_str(key, val)
        if s is not None:
            out[key] = s
    return out


def _write_m4a(path: str, changes: dict[str, str]) -> None:
    mp4 = MP4(path)
    if mp4.tags is None:
        mp4.add_tags()
    tags = mp4.tags
    for key, value in changes.items():
        if not value.strip():
            tags.pop(key, None)
            continue
        if key in ("trkn", "disk"):
            tags[key] = _parse_pair(value)
        elif key in _MP4_BOOL_KEYS:
            tags[key] = value.strip().lower() in ("1", "true", "yes", "y")
        elif key in _MP4_INT_KEYS:
            try:
                tags[key] = [int(v) for v in _split(value)]
            except ValueError:
                raise TagError(f"'{label_for('m4a', key)}' must be a number") from None
        elif key.startswith("----:"):
            tags[key] = [MP4FreeForm(v.encode("utf-8")) for v in _split(value)]
        else:
            tags[key] = _split(value)
    mp4.save()


# ---------------------------------------------------------------- flac

def _read_flac(path: str) -> dict[str, str]:
    audio = FLAC(path)
    grouped: dict[str, list[str]] = {}
    for key, value in audio.tags or []:
        grouped.setdefault(key.upper(), []).append(value)
    return {k: _join(v) for k, v in grouped.items()}


def _write_flac(path: str, changes: dict[str, str]) -> None:
    audio = FLAC(path)
    if audio.tags is None:
        audio.add_tags()
    for key, value in changes.items():
        if key in audio.tags:
            del audio.tags[key]
        values = _split(value) if key not in ("LYRICS", "UNSYNCEDLYRICS") else [value]
        if value.strip():
            audio.tags[key] = values
    audio.save()


# ---------------------------------------------------------------- public

_READERS = {"mp3": _read_mp3, "m4a": _read_m4a, "flac": _read_flac}
_WRITERS = {"mp3": _write_mp3, "m4a": _write_m4a, "flac": _write_flac}
_INFO = {"mp3": MP3, "m4a": MP4, "flac": FLAC}


def format_for(filename: str) -> str | None:
    return EXTENSIONS.get(os.path.splitext(filename)[1].lower())


def read_tags(fmt: str, path: str) -> dict[str, str]:
    return _READERS[fmt](path)


def read_length(fmt: str, path: str) -> float | None:
    try:
        return round(_INFO[fmt](path).info.length, 1)
    except Exception:
        return None


def write_tags(fmt: str, path: str, changes: dict[str, str]) -> None:
    if changes:
        _WRITERS[fmt](path, changes)
