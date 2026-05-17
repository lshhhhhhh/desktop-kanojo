"""Privacy guard: case-insensitive substring match against blocked window
titles. Lets callers ask "is the user looking at something we shouldn't ship
to a remote LLM right now?" before any screen-bearing request goes out.

This is a deliberately coarse first line of defense. It will:
- catch dedicated password managers (1Password, KeePass, Bitwarden) by title
- NOT catch in-page password fields inside a browser
- NOT catch banking sites unless the keyword is in the browser tab title

See docs (or README's privacy section, when written) for richer alternatives:
UI Automation tree walks for IsPassword fields, OCR-based heuristics, etc.
"""

from __future__ import annotations

from .win32 import get_active_window_title


class PrivacyGuard:
    def __init__(self, blocked_titles: list[str] | None = None) -> None:
        self._blocked: list[str] = []
        self.set_blocked_titles(blocked_titles or [])

    @classmethod
    def from_config(cls, cfg: dict) -> PrivacyGuard:
        privacy = (cfg.get("perception") or {}).get("privacy") or {}
        return cls(blocked_titles=privacy.get("blocked_window_titles") or [])

    def set_blocked_titles(self, titles: list[str]) -> None:
        # Case-folded substrings; we match against the current foreground
        # window title's casefolded form.
        self._blocked = [t.casefold() for t in titles if t and t.strip()]

    def blocked_titles(self) -> list[str]:
        return list(self._blocked)

    def check_active_window(self) -> tuple[bool, str]:
        """Returns (is_blocked, matched_title).

        `matched_title` is the actual foreground window title when blocked
        (useful for logging / UI). When not blocked, returns ("", "").
        """
        title = get_active_window_title()
        if not title:
            return False, ""
        low = title.casefold()
        for kw in self._blocked:
            if kw in low:
                return True, title
        return False, ""
