"""Tests for core/profile.py and the `tiktok user` command."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import typer
from typer.testing import CliRunner

from tiktok_cli.commands import user as user_cmd
from tiktok_cli.commands._table import render_profile
from tiktok_cli.core import profile
from tiktok_cli.core.errors import UserError

runner = CliRunner()
app = typer.Typer()


@app.command()
def _noop() -> None:
    """Typer single-command apps misparsed args in tests; keep >1 command."""


app.command(name="user")(user_cmd.user)

USER_INFO = {
    "user": {
        "id": "107955",
        "uniqueId": "tiktok",
        "nickname": "TikTok",
        "signature": "Your next discovery is waiting on TikTok.",
        "verified": True,
        "privateAccount": False,
        "secUid": "MS4wLjAB",
        "avatarLarger": "https://cdn.example.com/avatar.jpg",
        "createTime": 1500000000,
    },
    "stats": {
        "followerCount": 97100000,
        "followingCount": "2",
        "heartCount": 470200000,
        "videoCount": 1522,
        "friendCount": 2,
    },
}


def test_normalize_handle() -> None:
    assert profile.normalize_handle("@cool.user") == "cool.user"
    assert profile.normalize_handle("cool.user") == "cool.user"
    assert profile.normalize_handle("https://www.tiktok.com/@cool.user") == "cool.user"
    assert profile.normalize_handle("  spaced  ") == "spaced"


def test_normalize_profile() -> None:
    rec = profile.normalize_profile(USER_INFO)
    assert rec["id"] == "107955"
    assert rec["handle"] == "tiktok"
    assert rec["nickname"] == "TikTok"
    assert rec["signature"] == "Your next discovery is waiting on TikTok."
    assert rec["verified"] is True
    assert rec["private"] is False
    assert rec["follower_count"] == 97100000
    assert rec["following_count"] == 2
    assert rec["heart_count"] == 470200000
    assert rec["video_count"] == 1522
    assert rec["friend_count"] == 2
    assert rec["created"] == "2017-07-14"
    assert rec["url"] == "https://www.tiktok.com/@tiktok"


def test_normalize_profile_stats_v2_and_missing() -> None:
    info = {
        "user": {"id": "1", "uniqueId": "u"},
        "statsV2": {"followerCount": "100", "heart": 50, "videoCount": "3"},
    }
    rec = profile.normalize_profile(info)
    assert rec["follower_count"] == 100
    assert rec["heart_count"] == 50
    assert rec["video_count"] == 3
    assert rec["following_count"] is None
    assert rec["handle"] == "u"


def test_normalize_profile_empty() -> None:
    rec = profile.normalize_profile({})
    assert rec["id"] == ""
    assert rec["handle"] == ""
    assert rec["url"] == ""


def test_fetch_profile_builds_url_and_normalizes() -> None:
    scope = {"webapp.user-detail": {"userInfo": USER_INFO}}
    with patch.object(profile.post_page, "fetch_default_scope", return_value=scope) as fetch:
        rec = profile.fetch_profile("@tiktok")
    fetch.assert_called_once_with("https://www.tiktok.com/@tiktok")
    assert rec["handle"] == "tiktok"
    assert rec["follower_count"] == 97100000


def test_fetch_profile_accepts_profile_url() -> None:
    scope = {"webapp.user-detail": {"userInfo": USER_INFO}}
    with patch.object(profile.post_page, "fetch_default_scope", return_value=scope) as fetch:
        profile.fetch_profile("https://www.tiktok.com/@tiktok?lang=en")
    fetch.assert_called_once_with("https://www.tiktok.com/@tiktok")


def test_fetch_profile_missing_user_info() -> None:
    with (
        patch.object(profile.post_page, "fetch_default_scope", return_value={}),
        pytest.raises(UserError, match="could not load profile"),
    ):
        profile.fetch_profile("ghost")


def test_fetch_profile_rejects_bad_handle() -> None:
    with pytest.raises(UserError, match="invalid TikTok handle"):
        profile.fetch_profile("bad handle!!")


def test_render_profile() -> None:
    rec = profile.normalize_profile(USER_INFO)
    out = render_profile(rec)
    assert "@tiktok" in out or "tiktok" in out
    assert "97,100,000" in out
    assert "1,522" in out
    assert "TikTok" in out


class TestUserCommand:
    def test_table_output(self):
        rec = profile.normalize_profile(USER_INFO)
        with patch.object(user_cmd, "fetch_profile", return_value=rec) as fetch:
            result = runner.invoke(app, ["user", "@tiktok"])
        assert result.exit_code == 0, result.output
        assert "97,100,000" in result.output
        fetch.assert_called_once_with("@tiktok")

    def test_json_output(self):
        rec = profile.normalize_profile(USER_INFO)
        with patch.object(user_cmd, "fetch_profile", return_value=rec):
            result = runner.invoke(app, ["user", "tiktok", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["handle"] == "tiktok"
        assert data["follower_count"] == 97100000

    def test_user_error(self):
        with patch.object(
            user_cmd, "fetch_profile", side_effect=UserError("could not load profile @x")
        ):
            result = runner.invoke(app, ["user", "x"])
        assert result.exit_code == 1
