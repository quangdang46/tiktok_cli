"""tiktok-cli entry point.

Command modules are imported eagerly but MUST keep heavy deps
(yt_dlp, faster_whisper, mlx_whisper) lazy — imported inside functions —
so `tiktok --help` stays fast.

Discovery commands (info/search/list/tag/trending/discover) are SUSPENDED:
the underlying `tt` binary relies on TikTok endpoints that are aggressively
WAF-blocked for most IPs, so the commands were unreliable in practice. The
modules remain in ``commands/`` + ``core/discovery.py`` with full test
coverage — re-enable by restoring the imports and registrations below.
"""

import typer

from tiktok_cli.commands import batch, doctor, transcript

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
app.command(name="doctor")(doctor.doctor)
