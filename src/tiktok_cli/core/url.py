"""TikTok URL classification.

Ported from tiktok-transcript/lib/tiktok.js (classifyTikTokUrl,
videoIdFromUrl). Classifies a URL before we spend a yt-dlp call on it.
"""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlparse

UrlKind = Literal["video", "photo", "profile", "feed", "short", "other"]

_TIKTOK_HOSTS = frozenset(
    {
        "tiktok.com",
        "www.tiktok.com",
        "m.tiktok.com",
        "vm.tiktok.com",
        "vt.tiktok.com",
    }
)

_VIDEO_PATH = re.compile(r"^/@[\w.-]+/video/(\d+)")
_PHOTO_PATH = re.compile(r"^/@[\w.-]+/photo/(\d+)")
_BARE_VIDEO_PATH = re.compile(r"^/(?:v|video)/(\d+)")
_SHORT_PATH = re.compile(r"^/t/[\w-]+")
_PROFILE_PATH = re.compile(r"^/@[\w.-]+/?$")
_FEED_PATHS = frozenset({"/", "/foryou", "/following", "/explore", "/friends", "/live"})


def _hostname(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""


def is_tiktok_url(url: str) -> bool:
    """True when `url` parses to an http(s) URL on a known TikTok host."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    return _hostname(url).lower() in _TIKTOK_HOSTS


def classify_url(url: str) -> UrlKind:
    """Classify a TikTok URL into video/photo/profile/feed/short/other."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return "other"
    host = (parsed.hostname or "").lower()
    if host not in _TIKTOK_HOSTS:
        return "other"

    # Short links resolve to a video, but only after a redirect.
    if host.startswith("vm.") or host.startswith("vt.") or _SHORT_PATH.match(parsed.path):
        return "short"

    path = parsed.path.rstrip("/") or "/"
    if _VIDEO_PATH.match(parsed.path) or _BARE_VIDEO_PATH.match(parsed.path):
        return "video"
    if _PHOTO_PATH.match(parsed.path):
        return "photo"
    if path in _FEED_PATHS:
        return "feed"
    if _PROFILE_PATH.match(parsed.path):
        return "profile"
    return "other"


def video_id_from_url(url: str) -> str | None:
    """Extract the numeric video id from a canonical video URL.

    Returns None for shortlinks and non-video paths - those need yt-dlp
    resolution first.
    """
    try:
        path = urlparse(url).path
    except ValueError:
        return None
    match = _VIDEO_PATH.match(path) or _BARE_VIDEO_PATH.match(path)
    return match.group(1) if match else None
