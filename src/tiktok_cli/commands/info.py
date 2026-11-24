"""`tiktok info <url>` — video metadata via the tt SSR plane (no download)."""

from __future__ import annotations

import typer

from tiktok_cli.commands._table import emit_json, render_info, user_error_exit
from tiktok_cli.core import discovery
from tiktok_cli.core.errors import UserError


def info(
    url: str = typer.Argument(..., help="TikTok video URL or bare video id"),
    json_out: bool = typer.Option(False, "--json", help="Print raw JSON instead of a table"),
) -> None:
    try:
        record = discovery.video_info(url)
    except UserError as exc:
        user_error_exit(exc)
    if json_out:
        emit_json(record)
    else:
        print(render_info(record))
