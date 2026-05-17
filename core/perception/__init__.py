from .observer import ProactiveObserver
from .screen import Capture, ScreenObservation
from .win32 import get_active_window_title, get_idle_seconds

__all__ = [
    "Capture",
    "ProactiveObserver",
    "ScreenObservation",
    "get_active_window_title",
    "get_idle_seconds",
]
