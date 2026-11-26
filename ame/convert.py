"""FLAC -> MP3 conversion.

ffmpeg (with libmp3lame) does the audio. Tags are copied by ame itself rather than by
ffmpeg, so the Vorbis -> ID3 mapping is predictable: track/disc totals are merged into
TRCK/TPOS ("3/12"), comments and lyrics go to COMM/USLT, MusicBrainz ids go where Picard
puts them, and anything unrecognised becomes a TXXX frame. Embedded cover art is copied.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from typing import Any

from mutagen.id3 import ID3, UFID, ID3NoHeaderError

from . import art as ar
from . import tags as tg

QUALITY = {
    "v0": (["-q:a", "0"], "VBR V0 (~245 kbps, best)"),
    "v2": (["-q:a", "2"], "VBR V2 (~190 kbps)"),
    "320": (["-b:a", "320k"], "CBR 320 kbps"),
    "256": (["-b:a", "256k"], "CBR 256 kbps"),
    "192": (["-b:a", "192k"], "CBR 192 kbps"),
}
DEFAULT_QUALITY = "v0"

# Vorbis comment -> ID3 key (as used by tags.write_tags)
_VORBIS_TO_ID3 = {
    "TITLE": "TIT2", "ARTIST": "TPE1", "ALBUM": "TALB", "ALBUMARTIST": "TPE2",
    "ALBUM ARTIST": "TPE2", "DATE": "TDRC", "YEAR": "TDRC", "ORIGINALDATE": "TDOR",
    "GENRE": "TCON", "COMPOSER": "TCOM", "LYRICIST": "TEXT", "CONDUCTOR": "TPE3",
    "REMIXER": "TPE4", "BPM": "TBPM", "COMPILATION": "TCMP", "GROUPING": "TIT1",
    "SUBTITLE": "TIT3", "ARTISTSORT": "TSOP", "ALBUMARTISTSORT": "TSO2", "ALBUMSORT": "TSOA",
    "TITLESORT": "TSOT", "COMPOSERSORT": "TSOC", "PUBLISHER": "TPUB", "LABEL": "TPUB",
    "ORGANIZATION": "TPUB", "COPYRIGHT": "TCOP", "ENCODEDBY": "TENC", "LANGUAGE": "TLAN",
    "KEY": "TKEY", "INITIALKEY": "TKEY", "MOOD": "TMOO", "ISRC": "TSRC", "MEDIA": "TMED",
    "DISCSUBTITLE": "TSST", "ORIGINALALBUM": "TOAL", "ORIGINALARTIST": "TOPE",
    "COMMENT": "COMM::eng", "DESCRIPTION": "COMM::eng",
    "LYRICS": "USLT::eng", "UNSYNCEDLYRICS": "USLT::eng",
    "MUSICBRAINZ_ALBUMID": "TXXX:MusicBrainz Album Id",
    "MUSICBRAINZ_ARTISTID": "TXXX:MusicBrainz Artist Id",
    "MUSICBRAINZ_ALBUMARTISTID": "TXXX:MusicBrainz Album Artist Id",
    "MUSICBRAINZ_RELEASEGROUPID": "TXXX:MusicBrainz Release Group Id",
    "MUSICBRAINZ_RELEASETRACKID": "TXXX:MusicBrainz Release Track Id",
    "MUSICBRAINZ_WORKID": "TXXX:MusicBrainz Work Id",
    "MUSICBRAINZ_ALBUMSTATUS": "TXXX:MusicBrainz Album Status",
    "RELEASESTATUS": "TXXX:MusicBrainz Album Status",
    "MUSICBRAINZ_ALBUMTYPE": "TXXX:MusicBrainz Album Type",
    "RELEASETYPE": "TXXX:MusicBrainz Album Type",
    "RELEASECOUNTRY": "TXXX:MusicBrainz Album Release Country",
    "BARCODE": "TXXX:BARCODE", "CATALOGNUMBER": "TXXX:CATALOGNUMBER",
}
# handled specially
_TRACK_TOTAL = ("TRACKTOTAL", "TOTALTRACKS")
_DISC_TOTAL = ("DISCTOTAL", "TOTALDISCS")
_SKIP = {"ENCODER", "VENDOR", "WAVEFORMATEXTENSIBLE_CHANNEL_MASK", "ENCODING", "CODING_HISTORY"}


class ConvertError(Exception):
    pass


# ---------------------------------------------------------------- ffmpeg

def find_ffmpeg() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    # apps started outside a terminal may not have Homebrew on PATH
    for candidate in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"):
        if os.access(candidate, os.X_OK):
            return candidate
    return None


def ffmpeg_info() -> dict[str, Any]:
    path = find_ffmpeg()
    if not path:
        return {"available": False, "message": "ffmpeg isn't installed. On macOS: brew install ffmpeg · On Raspberry Pi: sudo apt install ffmpeg"}
    try:
        version = subprocess.run([path, "-hide_banner", "-version"], capture_output=True, text=True, timeout=10).stdout.split("\n")[0]
        encoders = subprocess.run([path, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError) as e:
        return {"available": False, "message": f"Couldn't run ffmpeg at {path}: {e}"}
    if "libmp3lame" not in encoders:
        return {"available": False, "message": f"{path} was built without the LAME MP3 encoder (libmp3lame)."}
    return {"available": True, "path": path, "version": version.replace("ffmpeg version ", "").split(" Copyright")[0]}


# ---------------------------------------------------------------- tags

def id3_changes_from_flac(vorbis: dict[str, str]) -> dict[str, str]:
    """Map ame's FLAC tag dict (upper-case keys, values joined with '; ') to ID3 keys."""
    out: dict[str, str] = {}
    totals = {"track": "", "disc": ""}
    for key, value in vorbis.items():
        if not value.strip() or key in _SKIP:
            continue
        if key in _TRACK_TOTAL:
            totals["track"] = totals["track"] or value.split(";")[0].strip()
        elif key in _DISC_TOTAL:
            totals["disc"] = totals["disc"] or value.split(";")[0].strip()
        elif key in ("TRACKNUMBER", "DISCNUMBER", "MUSICBRAINZ_TRACKID"):
            continue  # below
        else:
            id3_key = _VORBIS_TO_ID3.get(key, f"TXXX:{key}")
            if id3_key not in out:  # first of e.g. COMMENT/DESCRIPTION wins
                out[id3_key] = value
    for vkey, id3_key, total in (("TRACKNUMBER", "TRCK", totals["track"]), ("DISCNUMBER", "TPOS", totals["disc"])):
        num = vorbis.get(vkey, "").split(";")[0].strip()
        if num:
            out[id3_key] = f"{num}/{total}" if total and "/" not in num else num
    return out


# ---------------------------------------------------------------- converting

def output_path(directory: str, name: str, destination: str, subfolder: str) -> str:
    stem = os.path.splitext(name)[0]
    if destination == "subfolder":
        sub = (subfolder or "MP3").strip().strip("/\\")
        if not sub or sub in (".", "..") or "/" in sub or "\\" in sub:
            raise ConvertError(f"Invalid subfolder name '{subfolder}'")
        return os.path.join(directory, sub, stem + ".mp3")
    return os.path.join(directory, stem + ".mp3")


def convert_file(src: str, dst: str, quality: str, overwrite: bool) -> dict[str, Any]:
    """Convert one FLAC file. Returns {status: converted|exists, output, seconds, size}."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise ConvertError("ffmpeg isn't installed")
    if not os.path.isfile(src):
        raise ConvertError("File not found (renamed or deleted since the folder was read?)")
    if os.path.exists(dst) and not overwrite:
        return {"status": "exists", "output": dst}
    args, _ = QUALITY.get(quality, QUALITY[DEFAULT_QUALITY])

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    # Work on a hidden temp file in the destination folder, then move it into place,
    # so a failed or interrupted conversion never leaves a half-written .mp3 behind.
    tmp = os.path.join(os.path.dirname(dst), f".ame-convert-{uuid.uuid4().hex}.mp3")
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
             "-i", src, "-map", "0:a:0", "-vn", "-map_metadata", "-1",
             "-c:a", "libmp3lame", *args, "-write_xing", "1", "-id3v2_version", "0", tmp],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not os.path.exists(tmp):
            msg = (proc.stderr or "").strip().splitlines()
            raise ConvertError(msg[-1] if msg else f"ffmpeg exited with code {proc.returncode}")

        vorbis = tg.read_tags("flac", src)
        tg.write_tags("mp3", tmp, id3_changes_from_flac(vorbis))
        try:
            id3 = ID3(tmp)
        except ID3NoHeaderError:  # source had no tags at all
            id3 = ID3()
        track_id = vorbis.get("MUSICBRAINZ_TRACKID", "").split(";")[0].strip()
        if track_id:
            id3.add(UFID(owner="http://musicbrainz.org", data=track_id.encode()))
        found = ar.read_art("flac", src)
        if found:
            data, mime, w, h = ar.prepare_image(found[0], None)
            id3.save(tmp, v2_version=3)
            ar.embed_art("mp3", tmp, data, mime, w, h, replace=True)
            id3 = ID3(tmp)
        # ID3v2.3 is the most widely supported version (car stereos, Windows, older players)
        id3.save(tmp, v2_version=3)

        os.replace(tmp, dst)
        return {
            "status": "converted",
            "output": dst,
            "seconds": round(time.monotonic() - started, 1),
            "size": os.path.getsize(dst),
        }
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
