"""Privacy guard for screen-bearing requests.

Two-track matching against the foreground window:

1. **Process exe basename** (exact, case-insensitive) — e.g. `notepad.exe`.
   This is the strong signal. Process names are baked in by the developer
   and don't change with what the user is doing inside the app. On
   modern Windows (especially Win11) the window title often shows only
   the document name, so title-only matching misses most cases.

2. **Window title substring** (case-insensitive) — e.g. `"1Password"`,
   `"Online Banking"`. Catches things that *do* show up in the title
   (browser tab labels, dialog headers) where process granularity is
   too coarse (you don't want to blocklist all of `chrome.exe`).

Either rule matching is sufficient to block.

This is the cheap first line of defense. Future work: UIAutomation tree
walks to find IsPassword fields and blur just those pixels, but the
title/process combo already covers the high-value cases (password
managers, banking apps, secrets vaults) with zero false negatives on
the things it's supposed to catch.
"""

from __future__ import annotations

from .win32 import get_active_window_process_name, get_active_window_title


class PrivacyGuard:
    def __init__(
        self,
        blocked_titles: list[str] | None = None,
        blocked_processes: list[str] | None = None,
    ) -> None:
        self._blocked_titles: list[str] = []
        self._blocked_processes: set[str] = set()
        self.set_blocked_titles(blocked_titles or [])
        self.set_blocked_processes(blocked_processes or [])

    @classmethod
    def from_config(cls, cfg: dict) -> PrivacyGuard:
        privacy = (cfg.get("perception") or {}).get("privacy") or {}
        return cls(
            blocked_titles=privacy.get("blocked_window_titles") or [],
            blocked_processes=privacy.get("blocked_processes") or [],
        )

    def set_blocked_titles(self, titles: list[str]) -> None:
        # Case-folded substrings; we match against the current foreground
        # window title's casefolded form.
        self._blocked_titles = [t.casefold() for t in titles if t and t.strip()]

    def set_blocked_processes(self, processes: list[str]) -> None:
        # Exact basename match, casefolded.
        self._blocked_processes = {
            p.casefold() for p in processes if p and p.strip()
        }

    def blocked_titles(self) -> list[str]:
        return list(self._blocked_titles)

    def blocked_processes(self) -> list[str]:
        return sorted(self._blocked_processes)

    def check_active_window(self) -> tuple[bool, str]:
        """Returns (is_blocked, reason).

        `reason` is a human-readable description of why we blocked
        (process name and/or title) — used for the UI tooltip and the log.
        When not blocked, returns (False, "").
        """
        title = get_active_window_title()
        proc = get_active_window_process_name()

        # Process match wins — it's the higher-confidence signal.
        if proc and proc.casefold() in self._blocked_processes:
            reason = proc
            if title:
                reason = f"{proc} — {title}"
            return True, reason

        if title:
            low = title.casefold()
            for kw in self._blocked_titles:
                if kw in low:
                    return True, title

        return False, ""
