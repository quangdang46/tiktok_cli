"""Shared rendering helpers for the discovery commands.

tt emits flat JSONL records: videos carry ``id``/``desc``/``author``/
``play_count``/... while discover nodes carry ``kind``/``name``/``metric``/
``score``/... Extractors below are deliberately tolerant — every lookup tries
several key spellings and nested shapes so a schema tweak upstream degrades to
an empty cell instead of a crash.
"""

from __future__ import annotations

import io
import json
from typing import Any, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from tiktok_cli.core.errors import UserError

_DESC_MAX = 60


def _dig(record: dict, *paths: str) -> Any:
    """First non-None value across dotted paths ('author.nickname', 'play_count')."""
    for path in paths:
        cur: Any = record
        for part in path.split("."):
            if not isinstance(cur, dict):
                cur = None
                break
            cur = cur.get(part)
        if cur is not None:
            return cur
    return None


def _author(record: dict) -> str:
    author = _dig(record, "author", "author.nickname", "author.unique_id", "uploader")
    if isinstance(author, dict):
        return str(author.get("nickname") or author.get("unique_id") or "")
    return str(author or "")


def _desc(record: dict) -> str:
    desc = _dig(record, "desc", "title", "name", "signature")
    if desc is None:
        return ""
    text = str(desc).replace("\n", " ")
    if len(text) > _DESC_MAX:
        return text[: _DESC_MAX - 3] + "..."
    return text


def _plays(record: dict) -> Any:
    return _dig(record, "play_count", "stats.play_count", "view_count", "views", "metric")


def _score(record: dict) -> Any:
    return _dig(record, "score", "rank_score")


def _url(record: dict) -> str:
    url = _dig(record, "url", "webpage_url")
    if url:
        return str(url)
    author, vid = _author(record), _dig(record, "id", "video_id")
    if author and vid:
        return f"https://www.tiktok.com/@{author.lstrip('@')}/video/{vid}"
    return ""


def _fmt_count(value: Any) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float) and value.is_integer():
        return f"{int(value):,}"
    return str(value) if value is not None else ""


def _fmt_score(value: Any) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:.3f}"
    return str(value) if value is not None else ""


def render_video_table(records: list[dict]) -> str:
    """Ranked table for video/search/discover records. Returns a string."""
    if not records:
        return "no results"
    buf = io.StringIO()
    console = Console(file=buf, width=100, highlight=False)
    show_score = any(_score(r) is not None for r in records)
    table = Table(box=None, pad_edge=False, show_edge=False)
    table.add_column("#", justify="right", style="dim")
    if show_score:
        table.add_column("Score", justify="right")
    table.add_column("ID")
    table.add_column("Author")
    table.add_column("Plays", justify="right")
    table.add_column("Desc", overflow="ellipsis", max_width=_DESC_MAX)
    table.add_column("URL", style="dim", overflow="ellipsis")
    for i, rec in enumerate(records, 1):
        row = [
            str(i),
            _fmt_score(_score(rec)),
            str(_dig(rec, "id", "video_id") or ""),
            _author(rec),
            _fmt_count(_plays(rec)),
            _desc(rec),
            _url(rec),
        ]
        if not show_score:
            row.pop(1)
        table.add_row(*row)
    console.print(table)
    return buf.getvalue().rstrip()


def render_info(record: dict) -> str:
    """Compact key/value table for a single video record (`tiktok info`)."""
    buf = io.StringIO()
    console = Console(file=buf, width=100, highlight=False)
    table = Table(box=None, pad_edge=False, show_header=False)
    table.add_column(style="bold")
    table.add_column(overflow="fold")
    music_title = _dig(record, "music_title")
    music_author = _dig(record, "music_author")
    music = " — ".join(str(p) for p in (music_title, music_author) if p) or ""
    challenges = _dig(record, "challenges", "hashtags")
    tags = ", ".join(f"#{t}" for t in challenges) if isinstance(challenges, list) else ""
    duration = _dig(record, "duration")
    created = _dig(record, "create_time", "upload_date", "timestamp")
    pairs = [
        ("Title", _dig(record, "desc", "title") or ""),
        ("Author", _author(record)),
        ("ID", _dig(record, "id", "video_id") or ""),
        ("Plays", _fmt_count(_plays(record))),
        ("Likes", _fmt_count(_dig(record, "digg_count", "like_count", "likes"))),
        ("Comments", _fmt_count(_dig(record, "comment_count", "comments"))),
        ("Shares", _fmt_count(_dig(record, "share_count", "shares"))),
        ("Favorites", _fmt_count(_dig(record, "collect_count", "favorites"))),
        ("Music", music),
        (
            "Duration",
            f"{int(duration)}s" if isinstance(duration, (int, float)) else str(duration or ""),
        ),
        ("Created", str(created or "")),
        ("Tags", tags),
        ("URL", _url(record)),
    ]
    for label, value in pairs:
        if value != "" and value is not None:
            table.add_row(label, str(value))
    console.print(table)
    return buf.getvalue().rstrip()


def emit_records(records: list[dict], *, as_json: bool) -> None:
    """Print records as a table, or raw JSON with --json."""
    if as_json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        print(render_video_table(records))


def emit_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def user_error_exit(exc: UserError) -> NoReturn:
    """Print a UserError to stderr and exit with its exit_code."""
    typer.echo(str(exc), err=True)
    raise typer.Exit(exc.exit_code) from exc
