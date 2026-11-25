"""tiktok-cli entry point.

Command modules are imported eagerly but MUST keep heavy deps
(yt_dlp, faster_whisper, mlx_whisper) lazy — imported inside functions —
so `tiktok --help` stays fast.

Discovery commands search/trending/discover stay SUSPENDED: they rely
on TikTok's signed API plane, which is aggressively WAF-blocked for most
IPs. info/list/user work — info prefers the SSR page blob with yt-dlp as
fallback, list uses yt-dlp's flat profile playlist, user reads the
profile page's SSR blob. tag works too: /api/challenge/detail answers
unsigned once the session carries WAF cookies. The tt-backed modules
remain in ``commands/`` + ``core/discovery.py`` with full test coverage —
re-enable by restoring the imports and registrations below.
"""

import typer

from tiktok_cli.commands import (
    batch,
    doctor,
    download,
    info,
    list_cmd,
    tag,
    transcript,
    user,
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
app.command(name="doctor")(doctor.doctor)
app.command(name="user")(user.user)
app.command(name="info")(info.info)
app.command(name="list")(list_cmd.list_videos)
app.command(name="download")(download.download)
app.command(name="tag")(tag.tag)
