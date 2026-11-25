"""`tiktok tag <tag>` — hashtag metadata via the unsigned challenge/detail API."""

from __future__ import annotations

import typer

from tiktok_cli.commands._table import emit_json, render_tag, user_error_exit
from tiktok_cli.core.discovery import tag_info
from tiktok_cli.core.errors import UserError


def tag(
    name: str = typer.Argument(..., help="#tag, bare tag, or tiktok.com/tag/ URL"),
    json_out: bool = typer.Option(False, "--json", help="Print raw JSON instead of a table"),
) -> None:
    try:
        record = tag_info(name)
    except UserError as exc:
        user_error_exit(exc)
    if json_out:
        emit_json(record)
    else:
        print(render_tag(record))
