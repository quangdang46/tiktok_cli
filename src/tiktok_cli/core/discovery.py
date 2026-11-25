"""Discovery reads: video info and user posts — no login required.

Two planes, tried in order of richness:

- **SSR page blob** (``core.post_page``): post pages embed
  ``webapp.video-detail.itemInfo.itemStruct`` with statsV2, music and
  challenges — fields yt-dlp does not expose. Reached via curl_cffi past
  TikTok's JS challenge.
- **yt-dlp** (``core.downloader.YtdlpClient``): canonical resolution for
  shortlinks, bare ids, flat profile playlists, and cookie passthrough.

The ``tt``-binary wrappers below (search/trending/discover) remain
for the suspended commands only: TikTok's signed API plane is WAF-blocked
for most IPs, so those reads are unreliable in practice.

One ``/api/*`` endpoint answers without request signing once the session
carries WAF cookies — ``challenge/detail`` — which powers ``tag_info``.
Everything else on the API plane (item lists, search, user detail,
comments) silently returns an empty body without an ``X-Gnarly`` signature.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any
from urllib.parse import quote

from tiktok_cli.core import post_page
from tiktok_cli.core.downloader import YtdlpClient
from tiktok_cli.core.errors import UserError
from tiktok_cli.core.url import classify_url, photo_to_video_url

TT_INSTALL_HINT = "install: go install github.com/tamnd/tiktok-cli/cmd/tt@latest"

# TikTok WAF/challenge markers. Only consulted on failure paths — a successful
# JSONL stream can legitimately contain "403" inside numeric ids.
_WAF_MARKERS = ("walled", "challenge", "403")

_HANDLE_URL_RE = re.compile(r"tiktok\.com/@([A-Za-z0-9_.]+)", re.IGNORECASE)
_TAG_URL_RE = re.compile(r"tiktok\.com/tag/([^/?#]+)", re.IGNORECASE)
_HANDLE_RE = re.compile(r"^[A-Za-z0-9_.]+$")
_TAG_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
_BARE_ID_RE = re.compile(r"^\d{10,25}$")

_API_ORIGIN = "https://www.tiktok.com"
_API_PARAMS = (
    "aid=1988&app_name=tiktok_web&device_platform=web_pc"
    "&channel=tiktok_web&region=VN&language=en"
)

_DISCOVER_FLAGS = {
    "video": "--seed-video",
    "hashtag": "--seed-tag",
    "user": "--seed",
    "search": "--seed-search",
}


def tt_available() -> bool:
    """True when the `tt` binary is on PATH."""
    return shutil.which("tt") is not None


def _require_tt() -> None:
    if not tt_available():
        raise UserError(f"tt not installed — {TT_INSTALL_HINT}")


def run_tt(args: list[str], *, timeout: int = 120) -> list[dict]:
    """Run `tt <args> --output jsonl` and parse stdout as JSONL or a JSON array.

    Raises UserError on missing binary, non-zero exit, WAF challenge, empty
    output, or unparseable output.
    """
    _require_tt()
    cmd = ["tt", *args, "--output", "jsonl", "--quiet"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise UserError(
            f"tt timed out after {timeout}s",
            hint="the request may be rate-limited; retry with a smaller limit",
        ) from exc
    except OSError as exc:
        raise UserError(f"failed to run tt: {exc}") from exc

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    if proc.returncode != 0:
        if _looks_walled(stdout + "\n" + stderr):
            raise UserError(_WAF_MSG, hint=_WAF_HINT)
        tail = stderr.strip().splitlines()
        detail = tail[-1] if tail else f"exit code {proc.returncode}"
        raise UserError(f"tt failed: {detail}")

    records = _parse_records(stdout)
    if not records:
        if _looks_walled(stdout + "\n" + stderr):
            raise UserError(_WAF_MSG, hint=_WAF_HINT)
        raise UserError("tt returned no records")
    return records


_WAF_MSG = "TikTok served a WAF challenge — wait and retry or reduce rate"
_WAF_HINT = "tt video/user use the sturdier SSR plane; search/discover hit the signed API plane"


def _looks_walled(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _WAF_MARKERS)


def _parse_records(stdout: str) -> list[dict]:
    """Parse tt output as a JSON array or JSONL (one object per line)."""
    text = stdout.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        return [data]
    records: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records


def _normalize_handle(ref: str) -> str:
    """'@user', 'user', or a tiktok.com/@user URL -> bare handle."""
    ref = ref.strip()
    m = _HANDLE_URL_RE.search(ref)
    if m:
        return m.group(1)
    return ref.lstrip("@")


def _normalize_tag(tag: str) -> str:
    """'#tag', 'tag', or a tiktok.com/tag/tag URL -> bare tag name."""
    tag = tag.strip()
    m = _TAG_URL_RE.search(tag)
    if m:
        return m.group(1)
    return tag.lstrip("#")


def _to_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _record_from_item_struct(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize ``webapp.video-detail.itemInfo.itemStruct`` for the table renderers."""
    stats = item.get("statsV2") or item.get("stats") or {}
    author = item.get("author") or {}
    music = item.get("music") or {}
    video = item.get("video") or {}
    challenges = [
        c.get("title")
        for c in item.get("challenges") or []
        if isinstance(c, dict) and c.get("title")
    ]
    unique_id = author.get("uniqueId") or ""
    post_id = str(item.get("id") or "")
    return {
        "id": post_id,
        "desc": item.get("desc") or "",
        "title": item.get("desc") or "",
        "author": unique_id,
        "author_id": str(author.get("id") or ""),
        "play_count": _to_int(stats.get("playCount") or stats.get("play_count")),
        "digg_count": _to_int(stats.get("diggCount") or stats.get("digg_count")),
        "comment_count": _to_int(stats.get("commentCount") or stats.get("comment_count")),
        "share_count": _to_int(stats.get("shareCount") or stats.get("share_count")),
        "repost_count": _to_int(stats.get("repostCount") or stats.get("repost_count")),
        "favorite_count": _to_int(stats.get("collectCount") or stats.get("collect_count")),
        "create_time": _to_int(item.get("createTime") or item.get("create_time")),
        "duration": _to_int(video.get("duration") or item.get("duration")),
        "music_title": music.get("title") or "",
        "music_author": music.get("author") or "",
        "challenges": challenges,
        "url": (
            f"https://www.tiktok.com/@{unique_id}/video/{post_id}" if unique_id and post_id else ""
        ),
        "source": "tiktok-page",
    }


def _record_from_ytdlp(info: dict[str, Any]) -> dict[str, Any]:
    """Normalize a yt-dlp info/entry dict for the table renderers."""
    artists = info.get("artists")
    music_author = artists[0] if isinstance(artists, list) and artists else info.get("artist")
    post_id = str(info.get("id") or info.get("display_id") or "")
    uploader = info.get("uploader") or ""
    url = info.get("webpage_url") or info.get("url") or ""
    if not url and uploader and post_id:
        url = f"https://www.tiktok.com/@{uploader}/video/{post_id}"
    return {
        "id": post_id,
        "desc": info.get("description") or info.get("title") or "",
        "title": info.get("title") or "",
        "author": uploader,
        "author_id": str(info.get("uploader_id") or info.get("channel_id") or ""),
        "play_count": _to_int(info.get("view_count")),
        "digg_count": _to_int(info.get("like_count")),
        "comment_count": _to_int(info.get("comment_count")),
        "share_count": _to_int(info.get("repost_count")),
        "repost_count": _to_int(info.get("repost_count")),
        "favorite_count": _to_int(info.get("save_count") or info.get("favorite_count")),
        "create_time": _to_int(info.get("timestamp")),
        "duration": _to_int(info.get("duration")),
        "music_title": info.get("track") or "",
        "music_author": music_author or "",
        "challenges": info.get("tags") or [],
        "url": url,
        "source": "yt-dlp",
    }


def video_info(url: str, client: YtdlpClient | None = None) -> dict:
    """One video record for a URL or bare id.

    Post URLs (and bare numeric ids, resolved via ``/@_/video/``) go
    through the SSR page blob first — richer record, and it keeps working
    when yt-dlp's extractor breaks. yt-dlp is the fallback for everything
    else (shortlinks, odd paths, cookie-assisted reads).
    """
    client = client or YtdlpClient()
    # Bare numeric ids resolve through the @_/ placeholder author path.
    if _BARE_ID_RE.match(url.strip()):
        url = f"https://www.tiktok.com/@_/video/{url.strip()}"
    if classify_url(url) in ("video", "photo", "short"):
        item = post_page.fetch_item_struct(photo_to_video_url(url))
        if item:
            return _record_from_item_struct(item)
    info = client.extract_info(url)
    record = _record_from_ytdlp(info)
    if not record["id"] and not record["desc"]:
        raise UserError(
            "yt-dlp returned no video metadata",
            hint="check the URL is a public TikTok post",
        )
    return record


def search(keyword: str, limit: int = 20) -> list[dict]:
    """Mixed search hits — videos and users (`tt search`)."""
    return run_tt(["search", keyword, "-n", str(limit)])


def user_posts(handle: str, limit: int = 30, client: YtdlpClient | None = None) -> list[dict]:
    """A user's public videos via yt-dlp's flat profile playlist."""
    handle = _normalize_handle(handle)
    if not _HANDLE_RE.match(handle):
        raise UserError(
            f"invalid TikTok handle {handle!r}",
            hint="use a @handle, bare handle, or tiktok.com/@handle URL",
        )
    client = client or YtdlpClient()
    url = f"https://www.tiktok.com/@{handle}"
    data = client.extract_flat(url, limit=limit)
    entries = data.get("entries") or []
    return [_record_from_ytdlp(e) for e in entries if isinstance(e, dict)]


def _api_get_json(session: Any, path: str) -> dict:
    """GET ``path`` on www.tiktok.com/api and return the JSON body."""
    resp = session.get(
        f"{_API_ORIGIN}{path}",
        headers={"Referer": "https://www.tiktok.com/"},
        timeout=30,
    )
    try:
        data = resp.json()
    except ValueError as exc:
        raise UserError("TikTok API returned a non-JSON response") from exc
    if not isinstance(data, dict):
        raise UserError("TikTok API returned an unexpected response")
    return data


def tag_info(tag: str, session: Any | None = None) -> dict:
    """Hashtag metadata via ``/api/challenge/detail`` — unsigned, WAF-cookie only.

    Returns id/tag/title/desc plus video and view counts. Video *lists* under
    a hashtag still need the signed API plane (or login) — this is metadata only.
    """
    name = _normalize_tag(tag)
    if not _TAG_NAME_RE.match(name):
        raise UserError(
            f"invalid TikTok hashtag {tag!r}",
            hint="use a #tag, bare tag, or tiktok.com/tag/tag URL",
        )
    session = session or post_page.api_session()
    if session is None:
        raise UserError(
            "could not establish a TikTok session",
            hint="check network connectivity and retry",
        )
    data = _api_get_json(
        session, f"/api/challenge/detail/?challengeName={quote(name)}&{_API_PARAMS}"
    )
    info = data.get("challengeInfo") or {}
    challenge = info.get("challenge") or {}
    if not challenge.get("id"):
        raise UserError(
            f"hashtag #{name} not found",
            hint="check the tag name — it may not exist or may be region-locked",
        )
    # statsV2 carries real counts; the legacy stats objects can report 0.
    stats = info.get("statsV2") or info.get("stats") or challenge.get("stats") or {}
    share_meta = data.get("shareMeta") or {}
    announcement = info.get("challengeAnnouncement") or {}
    return {
        "id": str(challenge.get("id") or ""),
        "tag": name,
        "title": challenge.get("title") or name,
        "desc": (
            share_meta.get("desc")
            or announcement.get("body")
            or challenge.get("desc")
            or ""
        ),
        "video_count": _to_int(stats.get("videoCount")),
        "view_count": _to_int(stats.get("viewCount")),
        "url": f"https://www.tiktok.com/tag/{name}",
        "source": "tiktok-api",
    }


def hashtag_videos(tag: str, limit: int = 30) -> list[dict]:
    """Videos under a hashtag (`tt hashtag --videos`)."""
    return run_tt(["hashtag", _normalize_tag(tag), "--videos", "-n", str(limit)])


def trending(limit: int = 30) -> list[dict]:
    """Logged-out recommend feed (`tt trending`)."""
    return run_tt(["trending", "-n", str(limit)])


def discover(
    seeds: list[tuple[str, str]],
    top: int = 20,
    depth: int = 2,
    max_nodes: int | None = None,
) -> list[dict]:
    """Graph walk from seeds (`tt discover`).

    seeds is a list of (kind, value) pairs; kind is one of 'video',
    'hashtag', 'user', 'search', 'trending'. 'trending' takes an empty value.
    """
    args = ["discover"]
    for kind, value in seeds:
        kind = kind.strip().lower()
        if kind == "trending":
            args.append("--trending")
            continue
        flag = _DISCOVER_FLAGS.get(kind)
        if flag is None:
            raise UserError(
                f"unknown discover seed kind {kind!r}",
                hint="use one of: video, hashtag, user, search, trending",
            )
        value = value.strip()
        if not value:
            raise UserError(f"discover seed of kind {kind!r} needs a value")
        if kind == "user":
            value = _normalize_handle(value)
        elif kind == "hashtag":
            value = _normalize_tag(value)
        args += [flag, value]
    args += ["--depth", str(depth), "--top", str(top)]
    if max_nodes:
        args += ["--max-nodes", str(max_nodes)]
    # A graph walk makes many requests; give it more headroom than the default.
    return run_tt(args, timeout=600)
