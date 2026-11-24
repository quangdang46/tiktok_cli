"""`tiktok discover` — graph walk from seeds via `tt discover`.

Seed options mirror tt's flags: --seed-video, --seed-tag, --seed-user,
--seed-search (all repeatable) plus --trending. At least one seed is required.
"""

from __future__ import annotations

import typer

from tiktok_cli.commands._table import emit_records, user_error_exit
from tiktok_cli.core import discovery
from tiktok_cli.core.errors import UserError

# Module-level OptionInfo singletons: ruff B008 rejects typer.Option(...) calls
# in the defaults of list-typed parameters.
_SEED_VIDEO_OPT = typer.Option(None, "--seed-video", help="Video URL or id (repeatable)")
_SEED_TAG_OPT = typer.Option(None, "--seed-tag", help="#tag or tag URL (repeatable)")
_SEED_USER_OPT = typer.Option(None, "--seed-user", help="@handle or profile URL (repeatable)")
_SEED_SEARCH_OPT = typer.Option(None, "--seed-search", help="Search query (repeatable)")


def discover(
    seed_video: list[str] | None = _SEED_VIDEO_OPT,
    seed_tag: list[str] | None = _SEED_TAG_OPT,
    seed_user: list[str] | None = _SEED_USER_OPT,
    seed_search: list[str] | None = _SEED_SEARCH_OPT,
    trending: bool = typer.Option(False, "--trending", help="Seed from the trending feed"),
    depth: int = typer.Option(2, "--depth", help="Graph walk depth"),
    top: int = typer.Option(20, "--top", help="Max ranked results"),
    max_nodes: int | None = typer.Option(None, "--max-nodes", help="Cap on nodes visited"),
    json_out: bool = typer.Option(False, "--json", help="Print raw JSON instead of a table"),
) -> None:
    seeds: list[tuple[str, str]] = []
    seeds += [("video", v) for v in seed_video or []]
    seeds += [("hashtag", v) for v in seed_tag or []]
    seeds += [("user", v) for v in seed_user or []]
    seeds += [("search", v) for v in seed_search or []]
    if trending:
        seeds.append(("trending", ""))
    if not seeds:
        user_error_exit(
            UserError(
                "discover needs at least one seed",
                hint="use --seed-video/--seed-tag/--seed-user/--seed-search or --trending",
            )
        )
    try:
        records = discovery.discover(seeds, top=top, depth=depth, max_nodes=max_nodes)
    except UserError as exc:
        user_error_exit(exc)
    emit_records(records, as_json=json_out)
