"""Unit tests for core/errors.py - no network."""

from __future__ import annotations

import pytest

from tiktok_cli.core.errors import UserError, translate_download_error


def test_user_error_str_includes_hint() -> None:
    err = UserError("something broke", hint="try again later")
    assert str(err) == "error: something broke\nhint: try again later"
    assert err.msg == "something broke"
    assert err.hint == "try again later"
    assert err.exit_code == 1


def test_user_error_str_without_hint() -> None:
    err = UserError("plain failure")
    assert str(err) == "error: plain failure"


def test_user_error_custom_exit_code() -> None:
    err = UserError("not found", exit_code=2)
    assert err.exit_code == 2


@pytest.mark.parametrize(
    ("raw", "expected_msg_fragment"),
    [
        ("ERROR: [tiktok] Private video. Sign in if it's your video", "private"),
        ("This video is members-only content", "members-only"),
        ("Join this channel to watch", "members-only"),
        ("This video is not available in your country", "geo-blocked"),
        ("The site has blocked it in your country for this IP", "geo-blocked"),
        ("Sign in to confirm you are not a bot", "signed-in session"),
        ("Login required to view this post", "logged-in account"),
        ("This post requires authentication", "logged-in account"),
        ("Got an empty media response from the server", "login wall"),
        ("TikTok is not granting access to this video", "anonymous access"),
        ("Use --cookies-from-browser to pass cookies", "logged-in session"),
        ("Rate-limit reached, try again later", "rate-limiting"),
        ("Please confirm your age to continue", "age-restricted"),
        ("ERROR: Unsupported URL: https://example.com/x", "no extractor"),
        ("Video unavailable. This video has been removed", "unavailable"),
        ("Unable to download webpage: HTTP Error 403", "could not reach"),
        ("No supported JavaScript runtime could be found", "javascript runtime"),
    ],
)
def test_translate_known_errors(raw: str, expected_msg_fragment: str) -> None:
    err = translate_download_error(RuntimeError(raw))
    assert isinstance(err, UserError)
    assert expected_msg_fragment in err.msg.lower()


def test_translate_case_insensitive() -> None:
    err = translate_download_error(Exception("PRIVATE VIDEO - do not tell"))
    assert "private" in err.msg.lower()


def test_cookie_related_hints_suggest_flags() -> None:
    err = translate_download_error(Exception("Sign in to confirm you're not a bot"))
    assert "--cookies-from-browser" in (err.hint or "")
    assert "--cookies" in (err.hint or "")


def test_js_runtime_hint_mentions_deno_or_node() -> None:
    err = translate_download_error(Exception("no supported javascript runtime found"))
    assert "Deno" in (err.hint or "")
    assert "Node" in (err.hint or "")


def test_translate_unknown_error_falls_back() -> None:
    err = translate_download_error(Exception("ERROR: [tiktok] weird socket failure"))
    assert err.msg.startswith("Download failed:")
    assert "weird socket failure" in err.msg
    assert err.hint is not None


def test_translate_strips_error_prefix() -> None:
    err = translate_download_error(Exception("ERROR:   boom happened"))
    assert "ERROR:" not in err.msg
    assert "boom happened" in err.msg
