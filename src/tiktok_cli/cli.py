"""tiktok-cli entry point.

Command modules are imported eagerly but MUST keep heavy deps
(yt_dlp, faster_whisper, mlx_whisper) lazy — imported inside functions —
so `tiktok --help` stays fast (<100ms).
"""

import typer

from tiktok_cli.commands import (
    batch,
    discover,
    doctor,
    info,
    list_cmd,
    search,
    tag,
    transcript,
    trending,
)

app = typer.Typer(
    name="tiktok",
    help="TikTok URL -> local transcript files. No login, no LLM, no transcript websites.",
    add_completion=False,
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """TikTok URL -> local transcript CLI."""


app.command(name="transcript")(transcript.transcript)
app.command(name="batch")(batch.batch)
app.command(name="info")(info.info)
app.command(name="search")(search.search)
app.command(name="list")(list_cmd.list_videos)
app.command(name="tag")(tag.tag)
app.command(name="trending")(trending.trending)
app.command(name="discover")(discover.discover)
app.command(name="doctor")(doctor.doctor)
