"""`tiktok list <handle>` — a user's public videos via `tt posts`."""

from __future__ import annotations

import typer

from tiktok_cli.commands._table import emit_records, user_error_exit
from tiktok_cli.core import discovery
from tiktok_cli.core.errors import UserError


def list_videos(
    handle: str = typer.Argument(..., help="@handle, bare handle, or profile URL"),
    limit: int = typer.Option(30, "-n", "--limit", help="Max videos"),
    json_out: bool = typer.Option(False, "--json", help="Print raw JSON instead of a table"),
) -> None:
    try:
        records = discovery.user_posts(handle, limit=limit)
    except UserError as exc:
        user_error_exit(exc)
    emit_records(records, as_json=json_out)
