"""Artifact layout for processed videos (PLAN.md section 4).

Layout contract:

    <output_dir>/VIDEO_ID/{source.info.json, metadata.json, transcript.*}
    <output_dir>/index.jsonl          # append-only log

stdout carries only transcript/plain output; this module never prints.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tiktok_cli.core.errors import UserError

# yt-dlp info["id"] may contain characters outside this set; anything else is
# rejected rather than sanitized away so a bad id can't escape the output dir.
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")

# fmt -> canonical filename inside a video dir.
TRANSCRIPT_FORMATS: dict[str, str] = {
    "txt": "transcript.txt",
    "srt": "transcript.srt",
    "vtt": "transcript.vtt",
    "json": "transcript.json",
    "md": "transcript.md",
}

# index.jsonl statuses.
STATUS_CAPTION = "caption"
STATUS_WHISPER = "whisper"
STATUS_NO_CAPTIONS = "no-captions"
STATUS_NO_AUDIO = "no-audio"
STATUS_PHOTO_POST = "photo-post"
STATUS_FAILED = "failed"
STATUS_SKIPPED_CACHED = "skipped-cached"

# Every status above, in display order. Reporters must iterate this instead of
# hand-writing a format string, or a new status silently drops out of summaries
# and the per-status counts stop adding up to the total.
ALL_STATUSES = (
    STATUS_CAPTION,
    STATUS_WHISPER,
    STATUS_PHOTO_POST,
    STATUS_NO_CAPTIONS,
    STATUS_NO_AUDIO,
    STATUS_FAILED,
    STATUS_SKIPPED_CACHED,
)

# Statuses that produced something the caller asked for. Kept as a set so
# "success" is derived from the vocabulary rather than enumerated at each call
# site, which is how photo-post came to be counted as a failure in batch.
SUCCESS_STATUSES = frozenset(
    {
        STATUS_CAPTION,
        STATUS_WHISPER,
        STATUS_PHOTO_POST,
        STATUS_NO_CAPTIONS,  # documented as a legitimate outcome, not an error
        STATUS_NO_AUDIO,
        STATUS_SKIPPED_CACHED,
    }
)


def count_is_consistent(counts: dict[str, int], total: int) -> bool:
    """True when every processed URL landed in exactly one known status bucket."""
    return sum(counts.values()) == total and not (set(counts) - set(ALL_STATUSES))

_INDEX_FILENAME = "index.jsonl"


def sanitize_video_id(raw: str) -> str:
    """Validate a video id for use as a directory name.

    Accepts ``^[A-Za-z0-9_-]{6,}$``; raises ``UserError`` otherwise. No silent
    mangling: a rejected id is a data problem, not a naming problem.
    """
    if not isinstance(raw, str) or not _VIDEO_ID_RE.match(raw):
        raise UserError(
            f"invalid video id {raw!r}: expected ^[A-Za-z0-9_-]{{6,}}$",
            hint="The id must come from yt-dlp info['id'] or a TikTok URL.",
        )
    return raw


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _format_upload_date(value: Any) -> str | None:
    """Convert yt-dlp ``upload_date`` (YYYYMMDD) to ISO ``YYYY-MM-DD``."""
    if not value:
        return None
    s = str(value)
    if re.fullmatch(r"\d{8}", s):
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    # Already ISO-ish or unexpected shape: return as-is rather than dropping.
    return s


def compact_metadata(
    info: dict[str, Any],
    transcript_source: str,
    cue_count: int,
    language: str | None = None,
) -> dict[str, Any]:
    """Build the compact ``metadata.json`` payload from raw yt-dlp info.

    Keys: id, title, description, uploader, uploader_id, duration, upload_date,
    webpage_url, view_count, like_count, comment_count, transcript_source,
    cue_count, language, processed_at (UTC ISO8601).

    ``description`` is the post's caption. It is the only content a photo post
    has (no audio, no captions), and on a video it is often the real summary, so
    dropping it forced every caller to open ``source.info.json`` by hand.

    ``language`` falls back to yt-dlp's own tag when neither the caller nor the
    caption filename provided one, so an explicit ``-l`` and a detected tag are
    both preferred over a bare ``null``.
    """
    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "description": info.get("description"),
        "uploader": info.get("uploader"),
        "uploader_id": info.get("uploader_id"),
        "duration": info.get("duration"),
        "upload_date": _format_upload_date(info.get("upload_date")),
        "webpage_url": info.get("webpage_url"),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "comment_count": info.get("comment_count"),
        "transcript_source": transcript_source,
        "cue_count": cue_count,
        "language": language or info.get("language"),
        "processed_at": _utc_now_iso(),
    }


class VideoDir:
    """Filesystem handle for one video's artifact directory."""

    def __init__(self, output_dir: Path | str, video_id: str):
        self.output_dir = Path(output_dir)
        self.video_id = sanitize_video_id(video_id)
        self.path = self.output_dir / self.video_id

    @property
    def subs_dir(self) -> Path:
        return self.path / "subs"

    def is_processed(self) -> bool:
        """Idempotency check: transcript.json exists (PLAN.md section 3.4)."""
        return (self.path / TRANSCRIPT_FORMATS["json"]).exists()

    def ensure(self) -> Path:
        """Create the video dir (and subs/) if needed; return ``self.path``."""
        self.path.mkdir(parents=True, exist_ok=True)
        self.subs_dir.mkdir(parents=True, exist_ok=True)
        return self.path

    def source_info_path(self) -> Path:
        return self.path / "source.info.json"

    def metadata_path(self) -> Path:
        return self.path / "metadata.json"

    def transcript_path(self, fmt: str) -> Path:
        try:
            filename = TRANSCRIPT_FORMATS[fmt]
        except KeyError as exc:
            raise ValueError(
                f"unknown transcript format {fmt!r}; expected one of {sorted(TRANSCRIPT_FORMATS)}"
            ) from exc
        return self.path / filename

    def write_source_info(self, info: dict[str, Any], refresh: bool = False) -> Path:
        """Write raw yt-dlp info to ``source.info.json`` once.

        Skips if the file already exists unless ``refresh=True`` — the raw
        info is expensive to refetch and stable for a given video.
        """
        dest = self.source_info_path()
        if dest.exists() and not refresh:
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            json.dumps(info, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        return dest

    def write_metadata(self, compact: dict[str, Any]) -> Path:
        """Write the compact ``metadata.json`` payload."""
        dest = self.metadata_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            json.dumps(compact, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        return dest

    def write_transcripts(self, rendered: dict[str, str]) -> dict[str, Path]:
        """Write each rendered transcript format to its canonical filename.

        ``rendered`` maps format name (``txt``/``srt``/``vtt``/``json``/``md``)
        to file content. Returns ``{fmt: Path}`` for the files written.
        """
        self.ensure()
        written: dict[str, Path] = {}
        for fmt, content in rendered.items():
            dest = self.transcript_path(fmt)
            dest.write_text(content, encoding="utf-8")
            written[fmt] = dest
        return written


def append_index(output_dir: Path | str, record: dict[str, Any]) -> Path:
    """Append one JSON record to ``<output_dir>/index.jsonl``.

    Adds ``processed_at`` (UTC ISO8601) if the record doesn't already carry
    one. Creates the output dir if needed.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    entry = dict(record)
    entry.setdefault("processed_at", _utc_now_iso())
    index_path = out / _INDEX_FILENAME
    with index_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    return index_path


def read_index(output_dir: Path | str) -> Iterable[dict[str, Any]]:
    """Yield index.jsonl records as dicts (for future digest commands)."""
    index_path = Path(output_dir) / _INDEX_FILENAME
    if not index_path.exists():
        return
    with index_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)
