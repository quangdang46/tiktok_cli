"""`tiktok search <keyword>` — mixed video/user hits via `tt search`."""

from __future__ import annotations

import typer

from tiktok_cli.commands._table import emit_records, user_error_exit
from tiktok_cli.core import discovery
from tiktok_cli.core.errors import UserError


def search(
    keyword: str = typer.Argument(..., help="Search terms"),
    limit: int = typer.Option(20, "-n", "--limit", help="Max results"),
    json_out: bool = typer.Option(False, "--json", help="Print raw JSON instead of a table"),
) -> None:
    try:
        records = discovery.search(keyword, limit=limit)
    except UserError as exc:
        user_error_exit(exc)
    emit_records(records, as_json=json_out)
