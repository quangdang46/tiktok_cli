"""`tiktok info <url>` — video metadata, no download.

Primary source is the SSR page blob (statsV2, music, challenges); yt-dlp
is the fallback and handles shortlinks/bare ids. Cookies are opt-in for
posts behind a login wall.
"""

from __future__ import annotations

import typer

from tiktok_cli.commands._table import emit_json, render_info, user_error_exit
from tiktok_cli.core import discovery
from tiktok_cli.core.downloader import YtdlpClient
from tiktok_cli.core.errors import UserError


def info(
    url: str = typer.Argument(..., help="TikTok video/photo URL, shortlink, or bare video id"),
    json_out: bool = typer.Option(False, "--json", help="Print raw JSON instead of a table"),
    cookies_from_browser: str | None = typer.Option(
        None, "--cookies-from-browser", help="Browser to read cookies from (e.g. firefox)"
    ),
    cookies: str | None = typer.Option(None, "--cookies", help="Netscape cookies.txt file"),
) -> None:
    client = (
        YtdlpClient(cookies_from_browser=cookies_from_browser, cookies_file=cookies)
        if cookies_from_browser or cookies
        else None
    )
    try:
        record = discovery.video_info(url, client=client)
    except UserError as exc:
        user_error_exit(exc)
    if json_out:
        emit_json(record)
    else:
        print(render_info(record))
