"""`tiktok download <urls...>` — save public posts locally, no login.

Video URLs go through yt-dlp (``<author>-<id>.<ext>`` in the output dir).
Photo/slideshow posts have no video stream — their ``imagePost.images``
are fetched from the SSR page blob instead, into ``<id>/images/`` plus an
``images.json`` manifest. Re-runs skip posts already on disk unless
``--refresh``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from tiktok_cli.core import post_page
from tiktok_cli.core.downloader import YtdlpClient
from tiktok_cli.core.errors import UserError
from tiktok_cli.core.url import (
    classify_url,
    is_tiktok_url,
    photo_to_video_url,
    video_id_from_url,
)


def _is_photo_post(url: str, info: dict[str, Any]) -> bool:
    """Mirror of pipeline's check: /photo/ path, playlist type, or image flag."""
    if classify_url(url) == "photo":
        return True
    webpage_url = str(info.get("webpage_url") or "")
    return (
        "/photo/" in webpage_url
        or info.get("_type") == "playlist"
        or bool(info.get("is_image_post"))
    )


def _download_photo_post(url: str, out_dir: Path) -> list[Path]:
    """Download a slideshow's images + manifest; return saved media paths.

    ``/photo/`` pages no longer SSR ``itemStruct`` for anonymous clients —
    the same post id under ``/video/`` does, carrying ``imagePost``.
    """
    item = post_page.fetch_item_struct(photo_to_video_url(url))
    if not item:
        raise UserError(
            "could not load the post page",
            hint="the post may be private or TikTok is rate-limiting; retry later",
        )
    post_id = str(item.get("id") or video_id_from_url(url) or "post")
    dest = out_dir / post_id / "images"
    files = post_page.download_post_images(item, dest)
    if not files:
        raise UserError("the post has no downloadable images")
    post_page.write_images_manifest(out_dir / post_id, item, files)
    return files


def _download_one(
    url: str,
    out_dir: Path,
    client: YtdlpClient,
    *,
    refresh: bool,
) -> list[Path]:
    """Download one URL; return the saved file paths (stdout contract)."""
    fetch_url = photo_to_video_url(url)

    # Photo posts: no yt-dlp round-trip needed when the URL says /photo/.
    if classify_url(url) == "photo":
        post_id = video_id_from_url(url) or "post"
        if not refresh and (out_dir / post_id / "images").is_dir():
            return sorted((out_dir / post_id / "images").iterdir())
        return _download_photo_post(url, out_dir)

    info = client.extract_info(fetch_url) or {}
    video_id = str(info.get("id") or video_id_from_url(url) or "")

    if _is_photo_post(url, info):
        image_dir = out_dir / video_id / "images"
        if not refresh and image_dir.is_dir():
            return sorted(image_dir.iterdir())
        return _download_photo_post(fetch_url, out_dir)

    if not refresh and video_id:
        existing = sorted(out_dir.glob(f"*-{video_id}.*"))
        if existing:
            return [existing[0]]

    path, _info = client.download_video(fetch_url, out_dir)
    return [path]


def download(
    urls: Annotated[
        list[str],
        typer.Argument(help="TikTok video/photo URLs or shortlinks"),
    ],
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", "-o", help="Destination directory"),
    ] = Path("tiktok-downloads"),
    refresh: Annotated[
        bool,
        typer.Option("--refresh", help="Re-download existing posts"),
    ] = False,
    cookies_from_browser: Annotated[
        str | None,
        typer.Option("--cookies-from-browser", help="Browser to read cookies from (e.g. firefox)"),
    ] = None,
    cookies: Annotated[
        str | None,
        typer.Option("--cookies", help="Netscape cookies.txt file"),
    ] = None,
) -> None:
    """Download TikTok videos (mp4) and photo posts (images), no login."""
    client = YtdlpClient(
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies,
    )
    failures = 0
    for url in urls:
        if not is_tiktok_url(url):
            typer.echo(f"error: not a TikTok URL: {url}", err=True)
            failures += 1
            continue
        try:
            for path in _download_one(url, output_dir, client, refresh=refresh):
                print(path)
        except UserError as exc:
            typer.echo(str(exc), err=True)
            failures += 1
    if failures:
        raise typer.Exit(code=1)
