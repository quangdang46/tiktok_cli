"""User-facing error type and yt-dlp error translation.

Commands raise/catch UserError only; raw yt-dlp exceptions never reach the
CLI surface. translate_download_error maps yt-dlp's error text to a friendly
message plus an actionable hint.
"""

from __future__ import annotations

import re

_COOKIE_HINT = (
    "Retry with browser cookies: --cookies-from-browser firefox "
    "(or --cookies cookies.txt for an exported file)."
)

# Matched case-insensitively, in order, against yt-dlp's error text. First hit
# wins, so the specific rules must precede the general ones. Ported from
# omni-transcriber/src/transcriber/downloader.py.
_ERROR_RULES: tuple[tuple[str, str, str | None], ...] = (
    (
        "no supported javascript runtime",
        "yt-dlp needs a JavaScript runtime to read this site.",
        "Install Deno (recommended) or Node.js, then re-run.",
    ),
    (
        "private video",
        "That video is private.",
        "Only invited accounts can watch it. If yours can, add --cookies-from-browser firefox.",
    ),
    (
        "members-only",
        "That video is members-only.",
        f"{_COOKIE_HINT} The signed-in account needs the membership.",
    ),
    (
        "join this channel",
        "That video is members-only.",
        f"{_COOKIE_HINT} The signed-in account needs the membership.",
    ),
    (
        "not available in your country",
        "That video is geo-blocked in your region.",
        "Nothing to configure here - the site is refusing your region.",
    ),
    (
        "blocked it in your country",
        "That video is geo-blocked in your region.",
        "Nothing to configure here - the site is refusing your region.",
    ),
    (
        "sign in to confirm",
        "The site wants a signed-in session before it will hand over this media.",
        _COOKIE_HINT,
    ),
    ("login required", "That post requires a logged-in account.", _COOKIE_HINT),
    ("requires authentication", "That post requires a logged-in account.", _COOKIE_HINT),
    (
        "empty media response",
        "That post is behind a login wall.",
        _COOKIE_HINT,
    ),
    (
        "not granting access",
        "The site refused anonymous access to that post.",
        _COOKIE_HINT,
    ),
    # yt-dlp points at its own cookie flags whenever a site wants a session;
    # catching that phrase generalises to every extractor at once.
    (
        "--cookies-from-browser",
        "The site needs a logged-in session to hand over this media.",
        _COOKIE_HINT,
    ),
    ("rate-limit reached", "The site is rate-limiting this IP.", "Wait a few minutes, then retry."),
    (
        "confirm your age",
        "That video is age-restricted.",
        _COOKIE_HINT,
    ),
    (
        "unsupported url",
        "yt-dlp has no extractor for that URL.",
        "Check the link, or see the yt-dlp supported-sites list.",
    ),
    (
        "video unavailable",
        "That video is unavailable.",
        "It may have been removed, or the link may be wrong.",
    ),
    (
        "unable to download webpage",
        "Could not reach that page.",
        "Check the URL is right and the site is reachable.",
    ),
)

_ERROR_PREFIX = re.compile(r"^ERROR:\s*", re.IGNORECASE)


class UserError(Exception):
    """A failure the user can act on; carries a message and optional hint.

    Commands catch UserError, print `str(exc)` to stderr, and exit with
    `exit_code`. Never let a bare Exception escape a command.
    """

    def __init__(self, msg: str, hint: str | None = None, exit_code: int = 1) -> None:
        super().__init__(msg)
        self.msg = msg
        self.hint = hint
        self.exit_code = exit_code

    def __str__(self) -> str:
        text = f"error: {self.msg}"
        if self.hint:
            text += f"\nhint: {self.hint}"
        return text


def translate_download_error(exc: Exception) -> UserError:
    """Turn a yt-dlp (or other download) exception into a UserError."""
    text = str(exc)
    lowered = text.lower()
    for needle, message, hint in _ERROR_RULES:
        if needle in lowered:
            return UserError(message, hint=hint)
    return UserError(
        f"Download failed: {_ERROR_PREFIX.sub('', text).strip()}",
        hint="Re-run with -v to see yt-dlp's full output.",
    )
