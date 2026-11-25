"""TikTok profile lookup over the SSR plane (no login, no yt-dlp).

Profile pages embed ``webapp.user-detail.userInfo`` — ``user`` plus a
``stats`` block (follower/following/heart/video counts) — in the same
``__UNIVERSAL_DATA_FOR_REHYDRATION__`` blob post pages use. ``post_page``
already knows how to fetch that blob past TikTok's JS challenge, so this
module only has to normalize the shape.
"""

from __future__ import annotations

import re
import time
from typing import Any

from tiktok_cli.core import post_page
from tiktok_cli.core.errors import UserError

_HANDLE_RE = re.compile(r"^[A-Za-z0-9_.]+$")
_HANDLE_URL_RE = re.compile(r"tiktok\.com/@([A-Za-z0-9_.]+)", re.IGNORECASE)


def normalize_handle(ref: str) -> str:
    """'@user', 'user', or a tiktok.com/@user URL -> bare handle."""
    ref = ref.strip()
    m = _HANDLE_URL_RE.search(ref)
    if m:
        return m.group(1)
    return ref.lstrip("@")


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


def normalize_profile(user_info: dict[str, Any]) -> dict[str, Any]:
    """Flatten ``webapp.user-detail.userInfo`` into a stable record."""
    user = user_info.get("user") or {}
    stats = user_info.get("stats") or user_info.get("statsV2") or {}
    handle = user.get("uniqueId") or ""
    created = _to_int(user.get("createTime"))
    return {
        "id": str(user.get("id") or ""),
        "handle": handle,
        "nickname": user.get("nickname") or "",
        "signature": user.get("signature") or "",
        "verified": bool(user.get("verified")),
        "private": bool(user.get("privateAccount")),
        "sec_uid": user.get("secUid") or "",
        "avatar": user.get("avatarLarger") or user.get("avatarMedium") or "",
        "follower_count": _to_int(stats.get("followerCount")),
        "following_count": _to_int(stats.get("followingCount")),
        "heart_count": _to_int(stats.get("heartCount") or stats.get("heart")),
        "video_count": _to_int(stats.get("videoCount")),
        "friend_count": _to_int(stats.get("friendCount")),
        "create_time": created,
        "created": (time.strftime("%Y-%m-%d", time.gmtime(created)) if created else ""),
        "url": f"https://www.tiktok.com/@{handle}" if handle else "",
    }


def fetch_profile(handle: str) -> dict[str, Any]:
    """Fetch and normalize a public profile; raises UserError on failure."""
    handle = normalize_handle(handle)
    if not _HANDLE_RE.match(handle):
        raise UserError(
            f"invalid TikTok handle {handle!r}",
            hint="use a @handle, bare handle, or tiktok.com/@handle URL",
        )
    scope = post_page.fetch_default_scope(f"https://www.tiktok.com/@{handle}")
    user_info = (scope.get("webapp.user-detail") or {}).get("userInfo")
    if not user_info or not ((user_info.get("user") or {}).get("id")):
        raise UserError(
            f"could not load profile @{handle}",
            hint="the account may not exist, be private, or TikTok is rate-limiting; retry later",
        )
    return normalize_profile(user_info)
