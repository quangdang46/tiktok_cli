"""Fetch TikTok post pages (``/__UNIVERSAL_DATA_FOR_REHYDRATION__``) directly.

Used for photo/slideshow posts: yt-dlp cannot read ``/photo/`` URLs and its
extractor never exposes the ``imagePost`` image list, but the public web page
embeds the full ``itemStruct`` — including ``imagePost.images`` — once TikTok's
JavaScript challenge cookie is solved. The challenge is a SHA-256 proof-of-work
ported from gallery-dl's TikTok extractor.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

_HYDRATION_RE = re.compile(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', re.DOTALL
)
_CHALLENGE_MAX_ITER = 1_000_000
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def _b64d(data: str) -> bytes:
    return base64.b64decode(data + "=" * (-len(data) % 4))


def _b64r(data: bytes) -> str:
    """gallery-dl's b64rencode: standard b64 WITH '=' padding, no newlines."""
    return binascii.b2a_base64(data, newline=False).decode()


def _extr(text: str, start: str, end: str) -> str | None:
    i = text.find(start)
    if i < 0:
        return None
    j = text.find(end, i + len(start))
    return text[i + len(start) : j] if j >= 0 else None


def _challenge_field(html: str, field_id: str) -> str | None:
    """Hidden-input ``class`` attribute carrying base64 JSON (cs/wci/rci/rs)."""
    tag = _extr(html, f'id="{field_id}"', ">")
    return _extr(tag, 'class="', '"') if tag else None


def _default_scope(html: str) -> dict[str, Any]:
    match = _HYDRATION_RE.search(html)
    if not match:
        return {}
    try:
        return json.loads(match.group(1)).get("__DEFAULT_SCOPE__", {})
    except (ValueError, AttributeError):
        return {}


def _solve_challenge(html: str, session: Any) -> bool:
    """Solve TikTok's JS PoW challenge and set the ``_wafchallengeid`` cookie.

    Ported from gallery-dl ``extractor/tiktok.py:_solve_challenge``: find the
    smallest idx whose ``sha256(challenge_a + str(idx))`` equals the expected
    digest, then store the mutated challenge JSON (with ``d=idx``) as the
    ``wci`` cookie on ``.tiktok.com``.
    """
    cs = _challenge_field(html, "cs")
    wci = _challenge_field(html, "wci")
    rci = _challenge_field(html, "rci")
    rs = _challenge_field(html, "rs")
    if not cs or not wci:
        return False
    try:
        challenge = json.loads(_b64d(cs))
        preimage = _b64d(challenge["v"]["a"])
        expected = _b64d(challenge["v"]["c"])
    except (ValueError, KeyError, TypeError):
        return False

    idx = None
    for i in range(_CHALLENGE_MAX_ITER):
        if hashlib.sha256(preimage + str(i).encode()).digest() == expected:
            idx = i
            break
    if idx is None:
        return False

    challenge["d"] = _b64r(str(idx).encode())
    value = _b64r(json.dumps(challenge, separators=(",", ":")).encode())
    session.cookies.set(wci, value, domain=".tiktok.com")
    if rci and rs:
        session.cookies.set(rci, rs, domain=".tiktok.com")
    return True


def _item_struct_from_html(html: str) -> dict[str, Any] | None:
    scope = _default_scope(html)
    detail = scope.get("webapp.video-detail")
    if not detail:
        return None
    return (detail.get("itemInfo") or {}).get("itemStruct")


def _user_info_from_html(html: str) -> dict[str, Any] | None:
    scope = _default_scope(html)
    detail = scope.get("webapp.user-detail")
    if not detail:
        return None
    return (detail.get("userInfo") or {}).get("user")


def _new_session() -> Any:
    from curl_cffi import requests  # lazy: keeps module import cheap

    session = requests.Session(impersonate="chrome")
    session.headers.update({"Accept-Language": "en-US,en;q=0.9"})
    return session


def _get_html(session: Any, url: str) -> str:
    return session.get(url, headers={"User-Agent": _UA}, timeout=30).text


def _fetch_html(url: str, ready: Any) -> str | None:
    """GET ``url``; when ``ready(html)`` is False solve the JS challenge once and retry.

    ``ready`` is a predicate over the response HTML — it decides whether the
    page carries the data we came for (e.g. an itemStruct or a user record).
    Returns the satisfying HTML, or None when the data never shows up
    (private post, hard WAF, ...).
    """
    session = _new_session()

    try:
        html = _get_html(session, url)
    except Exception:  # noqa: BLE001 - any fetch failure means "no data"
        return None

    if ready(html):
        return html

    if _solve_challenge(html, session):
        try:
            html = _get_html(session, url)
        except Exception:  # noqa: BLE001 - any fetch failure means "no data"
            return None
        return html if ready(html) else None
    return None


def api_session(page_url: str = "https://www.tiktok.com/") -> Any | None:
    """Session warmed past TikTok's WAF challenge, for ``/api/*`` JSON calls.

    Fetches ``page_url`` once; when it serves the JS challenge, solves the
    proof-of-work and refetches so the ``_wafchallengeid``/``msToken``
    cookies are set. Returns None only when the landing fetch itself fails —
    unsigned API endpoints (e.g. ``challenge/detail``) answer once the
    session carries those cookies.
    """
    session = _new_session()
    session.headers.update({"User-Agent": _UA, "Accept": "application/json"})
    try:
        html = _get_html(session, page_url)
        if _solve_challenge(html, session):
            try:
                _get_html(session, page_url)
            except Exception:  # noqa: BLE001, S110 - best-effort; cookies already set by the solve
                pass
    except Exception:  # noqa: BLE001 - any fetch failure means no session
        return None
    return session


def fetch_default_scope(url: str) -> dict[str, Any]:
    """Fetch a TikTok page and return its ``__DEFAULT_SCOPE__`` blob.

    Works for any SSR-hydrated page — post pages (``webapp.video-detail``)
    and profile pages (``webapp.user-detail``) alike. Returns {} when the
    blob never materializes.
    """
    html = _fetch_html(url, lambda h: bool(_default_scope(h)))
    return _default_scope(html) if html else {}


def fetch_item_struct(url: str) -> dict[str, Any] | None:
    """Fetch a TikTok post page and return ``itemInfo.itemStruct``.

    ``url`` may be a ``/photo/`` or ``/video/`` post URL. Solves the JS
    challenge once when the first response lacks ``webapp.video-detail``.
    Returns None when the data is unavailable (private post, hard WAF, ...).
    """
    html = _fetch_html(url, lambda h: _item_struct_from_html(h) is not None)
    return _item_struct_from_html(html) if html else None


def fetch_user_info(url: str) -> dict[str, Any] | None:
    """Fetch a TikTok profile page and return ``userInfo.user``.

    ``url`` is a ``/@handle`` profile URL. Returns the ``user`` record only —
    callers wanting ``stats`` should use ``fetch_default_scope`` instead.
    """
    html = _fetch_html(url, lambda h: _user_info_from_html(h) is not None)
    return _user_info_from_html(html) if html else None


def post_image_urls(item_struct: dict[str, Any]) -> list[dict[str, Any]]:
    """Ordered image entries from ``itemStruct.imagePost.images``."""
    images = (item_struct.get("imagePost") or {}).get("images") or []
    out = []
    for img in images:
        urls = (img.get("imageURL") or {}).get("urlList") or []
        if urls:
            out.append(
                {
                    "url": urls[0],
                    "width": img.get("imageWidth"),
                    "height": img.get("imageHeight"),
                }
            )
    return out


def download_post_images(
    item_struct: dict[str, Any], dest_dir: Path, session: Any | None = None
) -> list[Path]:
    """Download slideshow images into ``dest_dir`` as ``image_01.jpg`` etc."""
    from curl_cffi import requests  # lazy

    dest_dir.mkdir(parents=True, exist_ok=True)
    if session is None:
        session = requests.Session(impersonate="chrome")
    saved: list[Path] = []
    for i, entry in enumerate(post_image_urls(item_struct), start=1):
        try:
            resp = session.get(entry["url"], timeout=60)
            resp.raise_for_status()
        except Exception:  # noqa: BLE001, S112 - skip images that fail to download
            continue
        ext = ".jpg"
        ctype = resp.headers.get("content-type", "")
        if "png" in ctype:
            ext = ".png"
        elif "webp" in ctype:
            ext = ".webp"
        path = dest_dir / f"image_{i:02d}{ext}"
        path.write_bytes(resp.content)
        saved.append(path)
    return saved


def write_images_manifest(
    video_dir_path: Path, item_struct: dict[str, Any], files: list[Path]
) -> Path:
    """Write ``images.json`` describing the downloaded slideshow."""
    entries = post_image_urls(item_struct)
    manifest = {
        "post_id": item_struct.get("id"),
        "desc": item_struct.get("desc"),
        "author": (item_struct.get("author") or {}).get("uniqueId"),
        "create_time": item_struct.get("createTime"),
        "image_count": len(entries),
        "images": [
            {
                "file": f.name,
                "url": e["url"],
                "width": e["width"],
                "height": e["height"],
            }
            for f, e in zip(files, entries)
        ],
        "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path = video_dir_path / "images.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return path
