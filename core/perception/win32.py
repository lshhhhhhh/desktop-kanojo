"""Lightweight Windows-native helpers (ctypes only, no pywin32).

Gracefully degrades to no-ops on non-Windows platforms.
"""

from __future__ import annotations

import sys

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("dwTime", wintypes.DWORD),
        ]

    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32

    def get_active_window_title() -> str:
        try:
            hwnd = _user32.GetForegroundWindow()
            if not hwnd:
                return ""
            length = _user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return ""
            buf = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value or ""
        except Exception:
            return ""

    def get_idle_seconds() -> float:
        try:
            lii = _LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(_LASTINPUTINFO)
            if not _user32.GetLastInputInfo(ctypes.byref(lii)):
                return 0.0
            tick = _kernel32.GetTickCount()
            # GetTickCount wraps every ~49 days; difference still arithmetic-correct mod 2**32
            return max(0.0, ((tick - lii.dwTime) & 0xFFFFFFFF) / 1000.0)
        except Exception:
            return 0.0

else:

    def get_active_window_title() -> str:
        return ""

    def get_idle_seconds() -> float:
        return 0.0
