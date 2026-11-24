"""VTT caption parsing and transcript rendering. Pure functions, no I/O beyond reading the VTT file.

Parsing logic is ported from the tiktok-transcript skill
(fetch-tiktok-transcript.py: parse_vtt / strip_vtt_markup / plain_text_from_cues)
and omni-transcriber formats.py renderers.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# A gap longer than this seconds starts a new paragraph in txt/md output.
DEFAULT_GAP_THRESHOLD = 2.0

# yt-dlp writes manual subs as `ID.LANG.vtt` and auto-captions with an `auto`
# marker in the name; manual subs always win over auto ones.
_AUTO_MARKERS = ("auto", "-auto", ".auto")


@dataclass
class Cue:
    start: float
    end: float
    start_time: str  # HH:MM:SS.mmm
    end_time: str  # HH:MM:SS.mmm
    text: str


def parse_time(value: str) -> float:
    """Parse `HH:MM:SS.mmm`, `MM:SS.mmm`, or a bare seconds value."""
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(value)
    except ValueError:
        raise ValueError(f"invalid timestamp: {value}") from None


def format_time(seconds: float) -> str:
    """`00:01:02.345` — always HH:MM:SS.mmm."""
    seconds = max(0.0, seconds)
    whole = int(seconds)
    millis = int(round((seconds - whole) * 1000))
    if millis == 1000:
        whole += 1
        millis = 0
    hours = whole // 3600
    minutes = (whole % 3600) // 60
    secs = whole % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def _fmt_srt(seconds: float) -> str:
    """`00:01:02,345` — SRT uses a comma before milliseconds."""
    return format_time(seconds).replace(".", ",")


def _fmt_human(seconds: float) -> str:
    """`[02:03]`, or `[1:02:03]` once the hour is non-zero."""
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"[{h}:{m:02d}:{s:02d}]" if h else f"[{m:02d}:{s:02d}]"


def strip_vtt_markup(text: str) -> str:
    """Remove WebVTT/ASS inline markup and normalize whitespace.

    Handles karaoke timestamps `<00:00:00.000>`, color/style tags `<c>`,
    `<b>`, `<i>`, ASS override blocks `{\\an8}`, the ASS hard-space `\\h`,
    and HTML entities (`&amp;`, `&lt;`, ...).
    """
    text = re.sub(r"<\d{2}:\d{2}:\d{2}\.\d{3}>", "", text)  # karaoke timestamps
    text = re.sub(r"<[^>]+>", "", text)  # <c>, <b>, <i>, <00:...>, etc.
    text = re.sub(r"\{[^}]*\}", "", text)  # ASS override blocks {\an8}
    text = text.replace("\\h", " ")  # ASS hard space
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def dedupe_cues(cues: list[Cue]) -> list[Cue]:
    """Drop cues whose text is identical to the previous kept cue.

    TikTok auto-captions frequently emit the same text on consecutive cues.
    """
    out: list[Cue] = []
    for cue in cues:
        if cue.text and (not out or out[-1].text != cue.text):
            out.append(cue)
    return out


def _skip_block(lines: list[str], index: int) -> int:
    """Skip a NOTE/STYLE block: everything up to the next blank line."""
    index += 1
    while index < len(lines) and lines[index].strip():
        index += 1
    return index


def parse_vtt(path: str | Path) -> list[Cue]:
    """Parse a WebVTT file into cues.

    Handles the WEBVTT header, NOTE/STYLE blocks (including multi-line),
    cue identifiers on their own line, `-->` timing lines with optional
    settings after the end time, inline tags, entities, and consecutive
    duplicate texts.
    """
    cues: list[Cue] = []
    lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip("﻿ ")
        if not line:
            index += 1
            continue
        if line == "WEBVTT" or line.startswith(("Kind:", "Language:")):
            index += 1
            continue
        if line.startswith("NOTE") or line.startswith("STYLE"):
            index = _skip_block(lines, index)
            continue
        # Cue identifier on its own line: the timing line follows.
        if "-->" not in line and index + 1 < len(lines) and "-->" in lines[index + 1]:
            index += 1
            line = lines[index].strip()
        if "-->" not in line:
            index += 1
            continue

        start_raw, end_raw = line.split("-->", 1)
        # Timing line may carry settings (align/position) after the end time.
        end_raw = end_raw.strip().split()[0] if end_raw.strip() else ""
        try:
            start = parse_time(start_raw)
            end = parse_time(end_raw)
        except ValueError:
            index += 1
            continue
        index += 1

        text_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index].strip())
            index += 1

        text = strip_vtt_markup(" ".join(text_lines))
        if text:
            cues.append(
                Cue(
                    start=round(start, 3),
                    end=round(end, 3),
                    start_time=format_time(start),
                    end_time=format_time(end),
                    text=text,
                )
            )

    return dedupe_cues(cues)


def _caption_lang(path: Path) -> str:
    """Extract the language tag from a yt-dlp caption filename.

    `12345.vie.vtt` -> `vie`; `12345.en-US.vtt` -> `en-US`; names without a
    language component -> "".
    """
    parts = path.stem.split(".")
    if len(parts) < 2:
        return ""
    return parts[-1].lower()


def _is_auto_caption(path: Path) -> bool:
    name = path.name.lower()
    return any(marker in name for marker in _AUTO_MARKERS)


def pick_caption_file(
    vtt_paths: list[str | Path],
    preference: tuple[str, ...] = ("vie", "vi", "en", "en-US"),
) -> Path | None:
    """Pick the best caption file from a list of .vtt paths.

    Ranking: manual subs beat auto-captions; then language preference order
    (exact match, then prefix either way); then lexicographically first name.
    Returns None for an empty list.
    """
    paths = [Path(p) for p in vtt_paths]
    if not paths:
        return None

    prefs = [p.lower() for p in preference]

    def rank(path: Path) -> tuple[int, int, str]:
        auto = 1 if _is_auto_caption(path) else 0
        lang = _caption_lang(path)
        lang_score = len(prefs)
        for i, pref in enumerate(prefs):
            if lang == pref or lang.startswith(pref) or pref.startswith(lang):
                lang_score = i
                break
        return (auto, lang_score, path.name)

    return sorted(paths, key=rank)[0]


def cues_to_paragraphs(cues: list[Cue], gap_threshold: float = DEFAULT_GAP_THRESHOLD) -> list[str]:
    """Merge cues into paragraphs, breaking on gaps longer than `gap_threshold`."""
    paragraphs: list[str] = []
    current: list[str] = []
    previous_end: float | None = None

    for cue in cues:
        text = cue.text.strip()
        if not text:
            continue
        if previous_end is not None and cue.start - previous_end > gap_threshold and current:
            paragraphs.append(" ".join(current))
            current = []
        current.append(text)
        previous_end = cue.end

    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


# --- Renderers (pure, each returns a str ending in exactly one "\n") ---------


def _ensure_newline(text: str) -> str:
    return text.rstrip("\n") + "\n"


def render_txt(cues: list[Cue], timestamps: bool = False) -> str:
    """Plain transcript: paragraphs, or `[mm:ss] text` lines with timestamps."""
    if timestamps:
        return _ensure_newline(
            "\n".join(f"{_fmt_human(cue.start)} {cue.text}" for cue in cues if cue.text)
        )
    return _ensure_newline("\n\n".join(cues_to_paragraphs(cues)))


def render_srt(cues: list[Cue]) -> str:
    """SubRip: numbered blocks `HH:MM:SS,mmm --> HH:MM:SS,mmm`."""
    blocks = [
        f"{i}\n{_fmt_srt(cue.start)} --> {_fmt_srt(cue.end)}\n{cue.text}"
        for i, cue in enumerate(cues, start=1)
    ]
    return _ensure_newline("\n\n".join(blocks))


def render_vtt(cues: list[Cue]) -> str:
    """WebVTT: `WEBVTT` header plus `HH:MM:SS.mmm --> HH:MM:SS.mmm` blocks."""
    blocks = [f"{cue.start_time} --> {cue.end_time}\n{cue.text}" for cue in cues]
    return _ensure_newline("\n\n".join(["WEBVTT", *blocks]))


def render_json(cues: list[Cue], meta: dict[str, Any] | None = None) -> str:
    """Stable schema for scripting: {source, language, duration, segments}."""
    meta = meta or {}
    duration = meta.get("duration")
    if duration is None and cues:
        duration = cues[-1].end
    payload = {
        "source": meta.get("source")
        or {
            k: meta[k]
            for k in ("title", "uploader", "uploader_id", "webpage_url", "upload_date")
            if k in meta
        },
        "language": meta.get("language"),
        "duration": duration,
        "segments": [{"start": c.start, "end": c.end, "text": c.text} for c in cues],
    }
    return _ensure_newline(json.dumps(payload, ensure_ascii=False, indent=2))


def render_md(cues: list[Cue], meta: dict[str, Any] | None = None) -> str:
    """Markdown: `# title`, metadata bullets, then timestamped cue lines."""
    meta = meta or {}
    title = meta.get("title") or "Transcript"
    bullets = []
    if meta.get("source") or meta.get("webpage_url"):
        bullets.append(f"- Source: {meta.get('webpage_url') or meta.get('source') or ''}")
    creator = meta.get("uploader") or meta.get("creator")
    if creator:
        bullets.append(f"- Creator: {creator}")
    if meta.get("duration") is not None:
        bullets.append(f"- Duration: {meta['duration']}s")
    if meta.get("language"):
        bullets.append(f"- Language: {meta['language']}")

    lines = [f"# {title}", ""]
    if bullets:
        lines.extend(bullets)
        lines.append("")
    lines.append("## Transcript")
    lines.append("")
    for cue in cues:
        lines.append(f"[{cue.start_time} -> {cue.end_time}] {cue.text}")
    return _ensure_newline("\n".join(lines))


_RENDERERS = {
    "txt": lambda cues, meta: render_txt(cues),
    "srt": lambda cues, meta: render_srt(cues),
    "vtt": lambda cues, meta: render_vtt(cues),
    "json": render_json,
    "md": render_md,
}


def render_all(
    cues: list[Cue],
    meta: dict[str, Any] | None,
    fmt: str,
    *,
    timestamps: bool = False,
) -> str | dict[str, str]:
    """Dispatch to a renderer by format name.

    `fmt` is one of txt|srt|vtt|json|md|all. `all` returns a dict of every
    format; anything else returns the rendered string.
    """
    if fmt == "all":
        return {name: render_all(cues, meta, name, timestamps=timestamps) for name in _RENDERERS}  # type: ignore[misc]
    if fmt == "txt" and timestamps:
        return render_txt(cues, timestamps=True)
    try:
        renderer = _RENDERERS[fmt]
    except KeyError:
        raise ValueError(f"unknown format: {fmt!r} (expected txt|srt|vtt|json|md|all)") from None
    return renderer(cues, meta)  # type: ignore[return-value]
