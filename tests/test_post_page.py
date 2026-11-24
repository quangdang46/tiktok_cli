"""Tests for core/post_page.py — TikTok page hydration + JS challenge."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from tiktok_cli.core import post_page


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode().rstrip("=")


def _make_challenge(idx: int = 42) -> tuple[str, dict]:
    """Build a solvable challenge payload like TikTok's hidden inputs."""
    preimage = b"secret-preimage"
    expected = hashlib.sha256(preimage + str(idx).encode()).digest()
    challenge = {
        "v": {"a": _b64e(preimage), "c": _b64e(expected)},
        "x": "extra",
    }
    return _b64e(json.dumps(challenge, separators=(",", ":")).encode()), challenge


def _html_with_scope(scope: dict) -> str:
    payload = json.dumps({"__DEFAULT_SCOPE__": scope})
    return f'<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{payload}</script></html>'


def test_b64d_padded_and_unpadded() -> None:
    raw = b"hello world"
    enc = base64.b64encode(raw).decode()
    assert post_page._b64d(enc) == raw
    assert post_page._b64d(enc.rstrip("=")) == raw


def test_b64r_keeps_padding() -> None:
    out = post_page._b64r(b"hi")
    assert out.endswith("=")
    assert base64.b64decode(out) == b"hi"


def test_extr_and_challenge_field() -> None:
    html = '<input id="cs" class="QUJD" data-x="1">'
    assert post_page._challenge_field(html, "cs") == "QUJD"
    assert post_page._challenge_field(html, "wci") is None


def test_default_scope_and_item_struct() -> None:
    scope = {"webapp.video-detail": {"itemInfo": {"itemStruct": {"id": "123", "desc": "hi"}}}}
    html = _html_with_scope(scope)
    assert post_page._default_scope(html)["webapp.video-detail"]
    item = post_page._item_struct_from_html(html)
    assert item == {"id": "123", "desc": "hi"}


def test_item_struct_missing() -> None:
    assert post_page._item_struct_from_html(_html_with_scope({})) is None
    assert post_page._item_struct_from_html("<html>no json</html>") is None


def test_solve_challenge_sets_cookie() -> None:
    cs_b64, _ = _make_challenge(idx=7)
    html = (
        f'<input id="cs" class="{cs_b64}">'
        '<input id="wci" class="d2ZpIj4=">'
        '<input id="rci" class="cj1y">'
        '<input id="rs" class="cnM9eA==">'
    )

    class FakeCookies:
        def __init__(self) -> None:
            self.store: dict[str, str] = {}

        def set(self, name, value, domain=None):
            self.store[name] = value

    class FakeSession:
        def __init__(self) -> None:
            self.cookies = FakeCookies()

    session = FakeSession()
    assert post_page._solve_challenge(html, session) is True
    assert "d2ZpIj4=" in session.cookies.store
    assert session.cookies.store["d2ZpIj4="]  # wci value is non-empty b64
    # 'rs' present -> rci cookie also set
    assert "cj1y" in session.cookies.store


def test_solve_challenge_no_fields() -> None:
    class S:
        cookies = None

    assert post_page._solve_challenge("<html></html>", S()) is False


def test_post_image_urls() -> None:
    item = {
        "imagePost": {
            "images": [
                {
                    "imageURL": {"urlList": ["https://cdn/1.jpg", "https://cdn/1hd.jpg"]},
                    "imageWidth": 1080,
                    "imageHeight": 1920,
                },
                {"imageURL": {"urlList": []}},
                {
                    "imageURL": {"urlList": ["https://cdn/2.jpg"]},
                    "imageWidth": 100,
                    "imageHeight": 100,
                },
            ]
        }
    }
    entries = post_page.post_image_urls(item)
    assert [e["url"] for e in entries] == ["https://cdn/1.jpg", "https://cdn/2.jpg"]
    assert entries[0]["width"] == 1080


def test_post_image_urls_empty() -> None:
    assert post_page.post_image_urls({}) == []
    assert post_page.post_image_urls({"imagePost": {"images": []}}) == []


def test_download_post_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    item = {
        "imagePost": {
            "images": [
                {"imageURL": {"urlList": ["https://cdn/a.jpg"]}, "imageWidth": 1, "imageHeight": 1},
                {"imageURL": {"urlList": ["https://cdn/b.png"]}, "imageWidth": 2, "imageHeight": 2},
            ]
        }
    }

    class Resp:
        def __init__(self, content: bytes, ctype: str) -> None:
            self.content = content
            self.headers = {"content-type": ctype}

        def raise_for_status(self) -> None:
            pass

    class FakeSession:
        def get(self, url, timeout=0):
            return Resp(b"\xff\xd8img", "image/jpeg" if "a.jpg" in url else "image/png")

    files = post_page.download_post_images(item, tmp_path, session=FakeSession())
    assert [f.name for f in files] == ["image_01.jpg", "image_02.png"]
    assert files[0].read_bytes() == b"\xff\xd8img"


def test_write_images_manifest(tmp_path: Path) -> None:
    item = {
        "id": "7707",
        "desc": "btc post",
        "author": {"uniqueId": "tutcolor2025"},
        "createTime": 1730000000,
        "imagePost": {
            "images": [
                {
                    "imageURL": {"urlList": ["https://cdn/1.jpg"]},
                    "imageWidth": 10,
                    "imageHeight": 20,
                }
            ]
        },
    }
    f = tmp_path / "image_01.jpg"
    f.write_bytes(b"x")
    manifest_path = post_page.write_images_manifest(tmp_path, item, [f])
    data = json.loads(manifest_path.read_text())
    assert data["post_id"] == "7707"
    assert data["author"] == "tutcolor2025"
    assert data["image_count"] == 1
    assert data["images"][0]["file"] == "image_01.jpg"
    assert data["images"][0]["width"] == 10
