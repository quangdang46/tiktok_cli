"""`tiktok user <handle>` — public profile stats via the SSR page plane."""

from __future__ import annotations

import typer

from tiktok_cli.commands._table import emit_json, render_profile, user_error_exit
from tiktok_cli.core.errors import UserError
from tiktok_cli.core.profile import fetch_profile


def user(
    handle: str = typer.Argument(..., help="@handle, bare handle, or profile URL"),
    json_out: bool = typer.Option(False, "--json", help="Print raw JSON instead of a table"),
) -> None:
    try:
        record = fetch_profile(handle)
    except UserError as exc:
        user_error_exit(exc)
    if json_out:
        emit_json(record)
    else:
        print(render_profile(record))
