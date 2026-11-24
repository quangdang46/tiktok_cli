"""`tiktok batch FILE` — process a list of TikTok URLs sequentially.

Reads one URL per line, skipping blank lines and `#` comments, dedupes
preserving order, then runs the same pipeline as `tiktok transcript` for
each URL. One bad URL never kills the batch: `pipeline.process_video`
returns failed results, and any unexpected exception is caught per-URL.

stdout carries only the per-video transcript.txt paths and the final
summary counts; the detail table goes to stderr.
"""

from __future__ import annotations

import types
from collections import Counter
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from tiktok_cli.core.errors import UserError

_OUT = Console()
_ERR = Console(stderr=True)

_ERROR_COL_WIDTH = 60
_FORMATS = ("txt", "srt", "vtt", "json", "md", "all")


def _read_urls(path: Path) -> list[str]:
    """Parse a batch file: strip whitespace, skip blanks/comments, dedupe."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UserError(f"Cannot read {path}: {exc}") from exc

    urls: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        url = line.strip()
        if not url or url.startswith("#"):
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)

    if not urls:
        raise UserError(
            f"No URLs found in {path}.",
            hint="Expected one TikTok URL per line; lines starting with # are comments.",
        )
    return urls


def _failed_result(url: str, output_dir: Path, error: str) -> types.SimpleNamespace:
    """Stand-in VideoResult for URLs that raised before producing one."""
    return types.SimpleNamespace(
        video_id="",
        url=url,
        status="failed",
        artifact_dir=output_dir,
        transcript_txt=None,
        cue_count=0,
        language=None,
        error=error,
    )


def _truncate(text: str | None, width: int = _ERROR_COL_WIDTH) -> str:
    if not text:
        return ""
    text = " ".join(text.split())
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def batch(
    file: Annotated[
        Path,
        typer.Argument(help="Text file with one TikTok URL per line (# comments allowed)."),
    ],
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            "-o",
            help="Directory for per-video artifact folders.",
        ),
    ] = Path("tiktok-transcripts"),
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="Whisper model name (fallback path)."),
    ] = "small",
    language: Annotated[
        str | None,
        typer.Option("--language", "-l", help="Whisper language hint; auto-detect by default."),
    ] = None,
    whisper: Annotated[
        str,
        typer.Option(
            "--whisper",
            help="auto = whisper only when no captions; always = skip captions; never = captions only.",
        ),
    ] = "auto",
    engine: Annotated[
        str,
        typer.Option("--engine", help="auto|faster|mlx (Whisper backend)."),
    ] = "auto",
    fmt: Annotated[
        str,
        typer.Option("--format", help="Output formats: txt|srt|vtt|json|md|all."),
    ] = "all",
    keep_audio: Annotated[
        bool,
        typer.Option("--keep-audio", help="Keep the downloaded audio after transcribing."),
    ] = False,
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Bypass the transcript.json cache and reprocess."),
    ] = False,
    cookies_from_browser: Annotated[
        str | None,
        typer.Option("--cookies-from-browser", help="Browser to read cookies from (e.g. firefox)."),
    ] = None,
    cookies: Annotated[
        str | None,
        typer.Option("--cookies", help="Netscape cookies.txt file for authenticated requests."),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show yt-dlp/whisper debug output on stderr."),
    ] = False,
) -> None:
    """Process every URL in FILE sequentially and print a summary."""
    if whisper not in ("auto", "always", "never"):
        raise typer.BadParameter("--whisper must be auto, always, or never")
    if engine not in ("auto", "faster", "mlx"):
        raise typer.BadParameter("--engine must be auto, faster, or mlx")
    if fmt not in _FORMATS:
        raise typer.BadParameter(f"--format must be one of: {', '.join(_FORMATS)}")

    try:
        urls = _read_urls(file)
    except UserError as exc:
        _ERR.print(str(exc))
        raise typer.Exit(code=exc.exit_code) from exc

    # Lazy import: keeps `tiktok --help` fast and lets tests inject a fake.
    from tiktok_cli.pipeline import process_video

    results = []
    for url in urls:
        try:
            result = process_video(
                url,
                output_dir,
                model=model,
                language=language,
                whisper=whisper,
                engine=engine,
                fmt=fmt,
                keep_audio=keep_audio,
                refresh=refresh,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies,
                verbose=verbose,
            )
        except Exception as exc:  # noqa: BLE001 — one bad URL never kills the batch
            _ERR.print(f"[yellow]warning:[/yellow] {url} raised {exc!r}; continuing.")
            result = _failed_result(url, output_dir, str(exc))
        results.append(result)

        if result.transcript_txt is not None:
            _OUT.print(str(result.transcript_txt))
        else:
            detail = result.error or result.status
            _ERR.print(f"[red]{result.url}[/red]: {result.status} — {detail}")

    table = Table(title=f"batch: {len(results)} URL(s)", show_lines=False)
    table.add_column("URL", overflow="fold", max_width=50)
    table.add_column("ID")
    table.add_column("Status")
    table.add_column("Cues", justify="right")
    table.add_column("Lang")
    table.add_column("Error", overflow="fold")
    for r in results:
        table.add_row(
            r.url,
            r.video_id or "-",
            r.status,
            str(r.cue_count),
            r.language or "-",
            _truncate(r.error),
        )
    _ERR.print(table)

    counts = Counter(r.status for r in results)
    ok = counts["ok"] + counts["caption"] + counts["whisper"]
    summary = (
        f"batch summary: total={len(results)} ok={ok} caption={counts['caption']} "
        f"whisper={counts['whisper']} failed={counts['failed']} "
        f"no-captions={counts['no-captions']} skipped={counts['skipped-cached']}"
    )
    _OUT.print(summary)

    if ok == 0 and counts["failed"] > 0 and counts["skipped-cached"] == 0:
        raise typer.Exit(code=1)
