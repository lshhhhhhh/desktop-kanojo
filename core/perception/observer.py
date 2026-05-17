from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from loguru import logger

from .win32 import get_active_window_title, get_idle_seconds

if TYPE_CHECKING:
    from core.session import ChatSession

    from .privacy import PrivacyGuard
    from .screen import Capture


OnSpeakFn = Callable[[str], "Awaitable[None] | None"]
IsBusyFn = Callable[[], bool]


class ProactiveObserver:
    """Watches the desktop and decides — via the LLM — whether to speak unprompted.

    Two-stage:
        1) cheap Gemini-Flash decision call returns JSON {should_speak, comment}
        2) only when should_speak is true does the comment surface in UI

    Triggers (any one fires evaluation, all subject to cooldowns):
        - timer: every `timer_seconds`
        - window switch: foreground window title changed
        - long idle: user hasn't touched mouse/keyboard for `idle_threshold`
    """

    def __init__(
        self,
        session: ChatSession,
        capture: Capture,
        on_speak: OnSpeakFn,
        *,
        enabled: bool = True,
        timer_seconds: float = 600,
        cooldown_seconds: float = 600,
        min_silence_after_user: float = 30,
        window_switch_enabled: bool = True,
        idle_threshold_seconds: float = 600,
        poll_interval: float = 5.0,
        is_busy: IsBusyFn | None = None,
        privacy: PrivacyGuard | None = None,
    ) -> None:
        self.session = session
        self.capture = capture
        self.on_speak = on_speak
        self.privacy = privacy
        self._enabled = enabled
        self.timer_seconds = timer_seconds
        self.cooldown_seconds = cooldown_seconds
        self.min_silence_after_user = min_silence_after_user
        self.window_switch_enabled = window_switch_enabled
        self.idle_threshold_seconds = idle_threshold_seconds
        self.poll_interval = poll_interval
        self._is_busy = is_busy

        self._last_proactive_at = 0.0
        self._last_user_at = time.monotonic()
        self._last_window_title = ""
        self._last_timer_check = time.monotonic()
        self._last_eval_at = 0.0
        self._idle_armed = True  # prevent retriggering on the same idle period

        self._running = False
        self._task: asyncio.Task | None = None

    # ------- state ----------------------------------------------------------

    def set_enabled(self, on: bool) -> None:
        self._enabled = bool(on)
        logger.info("proactive observer: enabled={}", self._enabled)

    def is_enabled(self) -> bool:
        return self._enabled

    def notify_user_spoke(self) -> None:
        self._last_user_at = time.monotonic()
        self._idle_armed = True  # re-arm idle trigger after any user activity

    def status_text(self) -> str:
        if not self._enabled:
            return "已关闭"
        now = time.monotonic()
        ago = now - self._last_proactive_at if self._last_proactive_at else None
        if ago is None:
            return "运行中（本会话尚未主动发言）"
        m = int(ago // 60)
        s = int(ago % 60)
        return f"运行中（上次主动发言 {m}分{s}秒前）"

    # ------- lifecycle ------------------------------------------------------

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.ensure_future(self._run())

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    # ------- core loop ------------------------------------------------------

    async def _run(self) -> None:
        logger.info(
            "proactive observer: starting (enabled={}, timer={}s, cooldown={}s)",
            self._enabled, self.timer_seconds, self.cooldown_seconds,
        )
        self._last_window_title = get_active_window_title()

        while self._running:
            try:
                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break

            if not self._enabled:
                continue

            try:
                triggers = self._collect_triggers()
                if not triggers:
                    continue
                if self._is_busy and self._is_busy():
                    logger.debug("proactive: UI busy, skipping eval")
                    continue
                logger.info("proactive: evaluating, triggers={}", triggers)
                await self._do_evaluation(triggers)
            except Exception as e:
                logger.exception("proactive observer loop error: {}", e)

        logger.info("proactive observer: stopped")

    def _collect_triggers(self) -> list[str]:
        now = time.monotonic()

        # absolute filters
        if now - self._last_user_at < self.min_silence_after_user:
            return []
        if (
            self._last_proactive_at
            and now - self._last_proactive_at < self.cooldown_seconds
        ):
            return []
        if now - self._last_eval_at < self.poll_interval * 1.5:
            # avoid duplicate eval within one polling tick
            return []

        triggers: list[str] = []

        if now - self._last_timer_check >= self.timer_seconds:
            triggers.append("timer")
            self._last_timer_check = now

        if self.window_switch_enabled:
            cur = get_active_window_title()
            if cur and cur != self._last_window_title:
                triggers.append(
                    f"window:{self._last_window_title!r}->{cur!r}"
                )
                self._last_window_title = cur

        idle = get_idle_seconds()
        if idle >= self.idle_threshold_seconds and self._idle_armed:
            triggers.append(f"idle:{int(idle)}s")
            self._idle_armed = False

        return triggers

    async def _do_evaluation(self, triggers: list[str]) -> None:
        now = time.monotonic()
        self._last_eval_at = now

        # Privacy guard: if the active window matches a blocked-title rule
        # (password managers, etc.), drop the eval entirely so no screenshot
        # is captured or shipped to a remote LLM.
        if self.privacy is not None:
            blocked, matched = self.privacy.check_active_window()
            if blocked:
                logger.info(
                    "proactive: privacy block, skipping eval (active: {!r})",
                    matched,
                )
                return

        context = {
            "window_title": get_active_window_title(),
            "idle_seconds": int(get_idle_seconds()),
            "triggers": triggers,
        }
        try:
            comment = await self.session.evaluate_and_speak(self.capture, context)
        except Exception as e:
            logger.warning("proactive eval failed: {}", e)
            return

        if not comment:
            return

        self._last_proactive_at = time.monotonic()
        res = self.on_speak(comment)
        if asyncio.iscoroutine(res):
            await res
