"""Cover art: find candidates online, and read/write embedded art and folder images.

Sources (no API keys needed):
  * MusicBrainz search -> Cover Art Archive (https://coverartarchive.org)
    MusicBrainz allows ~1 request/second per client and wants a descriptive User-Agent.
  * iTunes Search API (https://itunes.apple.com/search)
"""

from __future__ import annotations

import base64
import io
import json
import os
import ssl
import threading
import time
import urllib.parse
import urllib.request
from typing import Any

from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover

from .tags import COMMON_KEYS, read_tags

USER_AGENT = "ame/0.1 (audio metadata editor; https://github.com/)"
TIMEOUT = 20

# Tags that hold a MusicBrainz release id, per format.
MBID_KEYS = {
    "mp3": ["TXXX:MusicBrainz Album Id"],
    "m4a": ["----:com.apple.iTunes:MusicBrainz Album Id"],
    "flac": ["MUSICBRAINZ_ALBUMID"],
}


class ArtError(Exception):
    pass


# ---------------------------------------------------------------- http

def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # python.org builds on macOS ship without a CA bundle

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_CTX = _ssl_context()
_mb_lock = threading.Lock()
_mb_last = 0.0


def _get(url: str, accept: str = "*/*") -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_CTX) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise ArtError(f"{e.code} from {urllib.parse.urlsplit(url).netloc}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise ArtError(f"Couldn't reach {urllib.parse.urlsplit(url).netloc}: {reason}") from None


def _get_json(url: str) -> Any:
    return json.loads(_get(url, "application/json"))


def _musicbrainz(path: str, params: dict[str, str]) -> Any:
    """GET from the MusicBrainz API, keeping to its 1 request/second limit."""
    global _mb_last
    with _mb_lock:
        wait = 1.1 - (time.monotonic() - _mb_last)
        if wait > 0:
            time.sleep(wait)
        try:
            return _get_json(f"https://musicbrainz.org/ws/2/{path}?{urllib.parse.urlencode({**params, 'fmt': 'json'})}")
        finally:
            _mb_last = time.monotonic()


# ---------------------------------------------------------------- albums in a folder

def _first(value: str) -> str:
    return value.split(";", 1)[0].strip()


def group_albums(directory: str, files: list[dict[str, str]]) -> list[dict[str, Any]]:
    """files: [{format, file}] -> albums: [{id, album, artist, mbid, files: [{format, file, hasArt}]}]"""
    albums: dict[tuple[str, str], dict[str, Any]] = {}
    for f in files:
        fmt, name = f["format"], f["file"]
        path = os.path.join(directory, name)
        try:
            tags = read_tags(fmt, path)
        except Exception:
            continue
        keys = COMMON_KEYS[fmt]
        album = _first(tags.get(keys["album"], ""))
        artist = _first(tags.get(keys["albumartist"], "") or tags.get(keys["artist"], ""))
        mbid = next((_first(tags[k]) for k in MBID_KEYS[fmt] if tags.get(k)), "")
        key = (album.lower(), artist.lower())
        entry = albums.setdefault(key, {
            "id": f"{len(albums)}", "album": album, "artist": artist, "mbid": "", "files": [],
        })
        entry["mbid"] = entry["mbid"] or mbid
        entry["files"].append({"format": fmt, "file": name, "hasArt": has_art(fmt, path)})
    return sorted(albums.values(), key=lambda a: (a["album"] == "", a["album"].lower()))


# ---------------------------------------------------------------- searching

def _caa(kind: str, mbid: str, size: str = "") -> str:
    suffix = f"front-{size}" if size else "front"
    return f"https://coverartarchive.org/{kind}/{mbid}/{suffix}"


def _artist_credit(item: dict) -> str:
    return "".join(c.get("name", "") + c.get("joinphrase", "") for c in item.get("artist-credit", []))


def search_musicbrainz(album: str, artist: str, mbid: str = "") -> list[dict[str, Any]]:
    out = []
    if mbid:
        out.append({
            "source": "Cover Art Archive", "title": album, "artist": artist, "year": "",
            "detail": "exact match (MusicBrainz Album Id tag)",
            "thumb": _caa("release", mbid, "250"), "url": _caa("release", mbid, "1200"),
            "original": _caa("release", mbid),
        })
    if not album:
        return out
    query = f'releasegroup:"{album}"' + (f' AND artist:"{artist}"' if artist else "")
    data = _musicbrainz("release-group/", {"query": query, "limit": "6"})
    for rg in data.get("release-groups", []):
        if int(rg.get("score", 0)) < 60:
            continue
        out.append({
            "source": "Cover Art Archive",
            "title": rg.get("title", ""),
            "artist": _artist_credit(rg),
            "year": (rg.get("first-release-date") or "")[:4],
            "detail": rg.get("primary-type", "") or "",
            "thumb": _caa("release-group", rg["id"], "250"),
            "url": _caa("release-group", rg["id"], "1200"),
            "original": _caa("release-group", rg["id"]),
        })
    return out


def search_itunes(album: str, artist: str) -> list[dict[str, Any]]:
    term = " ".join(x for x in (artist, album) if x)
    if not term:
        return []
    data = _get_json("https://itunes.apple.com/search?" + urllib.parse.urlencode(
        {"term": term, "entity": "album", "limit": "6"}))
    out = []
    for r in data.get("results", []):
        art = r.get("artworkUrl100")
        if not art:
            continue
        out.append({
            "source": "iTunes",
            "title": r.get("collectionName", ""),
            "artist": r.get("artistName", ""),
            "year": (r.get("releaseDate") or "")[:4],
            "detail": f"{r['trackCount']} tracks" if r.get("trackCount") else "",
            "thumb": art.replace("100x100bb", "250x250bb"),
            "url": art.replace("100x100bb", "1200x1200bb"),
            "original": art.replace("100x100bb", "3000x3000bb"),
        })
    return out


def search(album: str, artist: str, mbid: str = "") -> dict[str, Any]:
    """Both sources; one failing doesn't stop the other. Returns {candidates, errors}."""
    candidates: list[dict[str, Any]] = []
    errors: list[str] = []
    for name, fn in (("MusicBrainz", lambda: search_musicbrainz(album, artist, mbid)),
                     ("iTunes", lambda: search_itunes(album, artist))):
        try:
            candidates += fn()
        except Exception as e:
            errors.append(f"{name}: {e}")
    return {"candidates": candidates, "errors": errors}


# ---------------------------------------------------------------- images

def prepare_image(data: bytes, max_size: int | None) -> tuple[bytes, str, int, int]:
    """Resize to fit within max_size x max_size (if larger) and return JPEG bytes.
    A JPEG that is already small enough is returned untouched. Returns (data, mime, w, h)."""
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise ArtError("Downloaded file isn't an image (the cover may not exist)") from None
    fmt = (img.format or "").upper()
    w, h = img.size
    if (not max_size or max(w, h) <= max_size) and fmt == "JPEG":
        return data, "image/jpeg", w, h
    if max_size and max(w, h) > max_size:
        img.thumbnail((max_size, max_size), Image.LANCZOS)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90, optimize=True)
    return buf.getvalue(), "image/jpeg", img.size[0], img.size[1]


_download_cache: dict[str, bytes] = {}


def download(url: str) -> bytes:
    if url not in _download_cache:
        _download_cache.clear()  # keep only the most recent image in memory
        _download_cache[url] = _get(url, "image/*")
    return _download_cache[url]


# ---------------------------------------------------------------- embedded art

def has_art(fmt: str, path: str) -> bool:
    try:
        if fmt == "mp3":
            return bool(ID3(path).getall("APIC"))
        if fmt == "m4a":
            return bool((MP4(path).tags or {}).get("covr"))
        if fmt == "flac":
            return bool(FLAC(path).pictures)
    except ID3NoHeaderError:
        return False
    except Exception:
        return False
    return False


def read_art(fmt: str, path: str) -> tuple[bytes, str] | None:
    try:
        if fmt == "mp3":
            pics = ID3(path).getall("APIC")
            front = next((p for p in pics if p.type == 3), pics[0] if pics else None)
            return (front.data, front.mime) if front else None
        if fmt == "m4a":
            covr = (MP4(path).tags or {}).get("covr")
            if covr:
                c = covr[0]
                return bytes(c), "image/png" if c.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
            return None
        if fmt == "flac":
            pics = FLAC(path).pictures
            front = next((p for p in pics if p.type == 3), pics[0] if pics else None)
            return (front.data, front.mime) if front else None
    except Exception:
        return None
    return None


def art_thumbnail(fmt: str, path: str, size: int = 160) -> str | None:
    """Embedded art as a small data: URL for the UI, or None."""
    found = read_art(fmt, path)
    if not found:
        return None
    try:
        data, mime, _, _ = prepare_image(found[0], size)
    except ArtError:
        return None
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def embed_art(fmt: str, path: str, data: bytes, mime: str, w: int, h: int, replace: bool) -> bool:
    """Embed as the front cover. Returns False if skipped because art exists and replace is off."""
    if not replace and has_art(fmt, path):
        return False
    if fmt == "mp3":
        try:
            id3 = ID3(path)
        except ID3NoHeaderError:
            id3 = ID3()
        id3.delall("APIC")
        id3.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
        version = 3 if id3.version and id3.version[1] == 3 else 4
        id3.save(path, v2_version=version)
    elif fmt == "m4a":
        mp4 = MP4(path)
        if mp4.tags is None:
            mp4.add_tags()
        imgfmt = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
        mp4.tags["covr"] = [MP4Cover(data, imageformat=imgfmt)]
        mp4.save()
    elif fmt == "flac":
        audio = FLAC(path)
        audio.clear_pictures()
        pic = Picture()
        pic.type, pic.mime, pic.desc, pic.data = 3, mime, "Cover", data
        pic.width, pic.height, pic.depth = w, h, 24
        audio.add_picture(pic)
        audio.save()
    return True
