from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.live2d_config import Live2DConfig
from core.voice import SentenceBuffer, Speaker, TTSBackend

if TYPE_CHECKING:
    from core.session import ChatSession


CHAT_STYLE = """
#chatPanel {
    background-color: rgba(15, 15, 25, 220);
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
}
QTextEdit {
    background-color: rgba(255, 255, 255, 10);
    color: #f5f0f5;
    border: 1px solid rgba(255, 182, 217, 60);
    border-radius: 6px;
    padding: 8px;
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 11pt;
    selection-background-color: rgba(255, 182, 217, 120);
}
QLineEdit {
    background-color: rgba(255, 255, 255, 18);
    color: #ffffff;
    border: 1px solid rgba(255, 182, 217, 80);
    border-radius: 6px;
    padding: 6px 10px;
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 11pt;
}
QLineEdit:focus { border: 1px solid rgba(255, 182, 217, 200); }
QPushButton {
    background-color: rgba(255, 130, 180, 100);
    color: white;
    border: none;
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 11pt;
    font-weight: bold;
}
QPushButton:hover { background-color: rgba(255, 130, 180, 160); }
QPushButton:disabled { background-color: rgba(120, 120, 120, 80); color: #aaa; }
"""

TITLE_BAR_STYLE = """
#titleBar {
    background-color: rgba(15, 15, 25, 200);
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
    border-bottom: 1px solid rgba(255, 182, 217, 60);
}
#titleBar QLabel {
    color: rgba(255, 182, 217, 180);
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 10pt;
    padding-left: 4px;
}
"""

CLOSE_BTN_STYLE = """
QPushButton {
    background-color: rgba(255, 80, 100, 200);
    color: white;
    border: none;
    border-radius: 14px;
    font-size: 14pt;
    font-weight: bold;
    padding: 0;
}
QPushButton:hover { background-color: rgba(255, 60, 80, 240); }
"""

SETTINGS_BTN_FLOAT_STYLE = """
QPushButton {
    background-color: rgba(120, 160, 220, 180);
    color: white;
    border: none;
    border-radius: 14px;
    font-size: 14pt;
    padding: 0;
}
QPushButton:hover { background-color: rgba(140, 180, 240, 240); }
"""


class TitleBar(QFrame):
    """Top strip that doubles as the window-drag handle. Houses the settings
    and close buttons. Clicking-and-dragging anywhere in the strip (except on
    a button) moves the parent window."""

    settings_clicked = Signal()
    close_clicked = Signal()
    proactive_toggled = Signal(bool)  # True = she can see; False = blindfolded

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("titleBar")
        self.setFixedHeight(34)
        self.setStyleSheet(TITLE_BAR_STYLE)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(6)

        self.title = QLabel("imouto", self)
        layout.addWidget(self.title)
        self.status = QLabel("", self)
        self.status.setStyleSheet(
            "color: rgba(255, 255, 255, 120); padding-left: 10px;"
        )
        layout.addWidget(self.status)
        layout.addStretch(1)

        # Privacy indicator: hidden by default, flips visible when the
        # active window matches a blocked title. Hard red + lock icon to
        # be unmissable; tooltip explains the gate is preventing screen
        # data from going to a remote LLM.
        self.privacy_label = QLabel("", self)
        self.privacy_label.setStyleSheet(
            "color: #ff4040; font-weight: bold; padding: 0 8px;"
        )
        self.privacy_label.hide()
        layout.addWidget(self.privacy_label)

        # Eye toggle: lets the user manually blind her to the screen even
        # when no blocklist rule matches. 👁 = proactive screen-eval enabled,
        # 🙈 = paused. Clicking flips the state and emits proactive_toggled.
        self.eye_btn = QPushButton("👁", self)
        self.eye_btn.setFixedSize(26, 26)
        self.eye_btn.setCheckable(True)
        self.eye_btn.setStyleSheet(SETTINGS_BTN_FLOAT_STYLE)
        self.eye_btn.setToolTip("她正在看着屏幕（点击让她闭眼）")
        self.eye_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.eye_btn.toggled.connect(self._on_eye_toggled)
        layout.addWidget(self.eye_btn)

        self.settings_btn = QPushButton("⚙", self)
        self.settings_btn.setFixedSize(26, 26)
        self.settings_btn.setStyleSheet(SETTINGS_BTN_FLOAT_STYLE)
        self.settings_btn.setToolTip("设置")
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.clicked.connect(self.settings_clicked.emit)
        layout.addWidget(self.settings_btn)

        self.close_btn = QPushButton("✕", self)
        self.close_btn.setFixedSize(26, 26)
        self.close_btn.setStyleSheet(CLOSE_BTN_STYLE)
        self.close_btn.setToolTip("关闭")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.close_clicked.emit)
        layout.addWidget(self.close_btn)

        self._drag_origin: QPoint | None = None

    def set_status(self, text: str, color: str = "rgba(255, 255, 255, 120)") -> None:
        """Update the small subtitle inside the title bar (server status etc.)."""
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}; padding-left: 10px;")

    def _on_eye_toggled(self, blinded: bool) -> None:
        if blinded:
            self.eye_btn.setText("🙈")
            self.eye_btn.setToolTip("她在闭眼，看不到屏幕（点击恢复）")
        else:
            self.eye_btn.setText("👁")
            self.eye_btn.setToolTip("她正在看着屏幕（点击让她闭眼）")
        self.proactive_toggled.emit(not blinded)

    def set_proactive_enabled(self, enabled: bool) -> None:
        """Sync the eye button to an external enabled-state change (e.g.
        flipped from the settings dialog). Avoids re-emitting the signal."""
        was_blocking = self.eye_btn.blockSignals(True)
        self.eye_btn.setChecked(not enabled)
        self._on_eye_toggled(not enabled)
        self.eye_btn.blockSignals(was_blocking)

    def set_privacy_active(self, active: bool, reason: str = "") -> None:
        """Toggle the red privacy indicator. When active, the title bar
        shows '🔒 Privacy' and screen-bearing requests are blocked."""
        if active:
            self.privacy_label.setText("🔒 Privacy")
            self.privacy_label.setToolTip(
                f"前台窗口命中黑名单（{reason}）。"
                f"\n屏幕内容不会发送到远程 LLM。"
            )
            self.privacy_label.show()
        else:
            self.privacy_label.hide()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            win = self.window()
            self._drag_origin = (
                event.globalPosition().toPoint() - win.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            win = self.window()
            win.move(event.globalPosition().toPoint() - self._drag_origin)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_origin = None
        super().mouseReleaseEvent(event)


COLOR_USER_PREFIX = QColor("#ffb6d9")
COLOR_USER_TEXT = QColor("#ffffff")
COLOR_ASST_PREFIX = QColor("#a0e0ff")
COLOR_ASST_TEXT = QColor("#f5f0f5")
COLOR_SYS_NOTE = QColor("#888888")


EMOTION_TAG_RE = re.compile(r"^\s*\[心情[:：]\s*([^\]]+?)\s*\]\s*")


def _bold_format(color: QColor) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(color)
    f = QFont()
    f.setBold(True)
    fmt.setFont(f)
    return fmt


def _plain_format(color: QColor, italic: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(color)
    if italic:
        f = QFont()
        f.setItalic(True)
        fmt.setFont(f)
    return fmt


class ChatPanel(QFrame):
    user_message = Signal(str)
    screenshot_requested = Signal(str)  # carries the input-box text (may be empty)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chatPanel")
        self.setStyleSheet(CHAT_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.output = QTextEdit(self)
        self.output.setReadOnly(True)
        layout.addWidget(self.output, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("发消息…  Enter 发送  ·  📷 带截屏一起发")
        self.input.returnPressed.connect(self._emit_send)
        row.addWidget(self.input, 1)

        self.screenshot_btn = QPushButton("📷", self)
        self.screenshot_btn.setToolTip("截屏发送：有输入文字就一并发，空白则让她随便评论")
        self.screenshot_btn.setFixedWidth(40)
        self.screenshot_btn.clicked.connect(self._emit_screenshot)
        row.addWidget(self.screenshot_btn)

        self.send_btn = QPushButton("发送", self)
        self.send_btn.clicked.connect(self._emit_send)
        row.addWidget(self.send_btn)
        layout.addLayout(row)

    def _emit_screenshot(self) -> None:
        text = self.input.text().strip()
        self.input.clear()
        self.screenshot_requested.emit(text)

    def _emit_send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.user_message.emit(text)

    def set_input_enabled(self, enabled: bool) -> None:
        self.input.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
        self.screenshot_btn.setEnabled(enabled)
        if enabled:
            self.input.setFocus()

    def _scroll_to_bottom(self) -> None:
        bar = self.output.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _cursor_at_end(self) -> QTextCursor:
        cur = self.output.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        return cur

    def _maybe_new_block(self, cur: QTextCursor) -> None:
        """Insert a paragraph break unless the document is empty or already at a fresh block."""
        doc = self.output.document()
        if doc.isEmpty():
            return
        if cur.atBlockStart() and cur.atBlockEnd():
            return
        cur.insertBlock()

    def begin_user(self, text: str, display_prefix: str = "你") -> None:
        cur = self._cursor_at_end()
        self._maybe_new_block(cur)
        cur.insertText(f"{display_prefix} · ", _bold_format(COLOR_USER_PREFIX))
        cur.insertText(text, _plain_format(COLOR_USER_TEXT))
        self.output.setTextCursor(cur)
        self._scroll_to_bottom()

    def begin_assistant(self, display_prefix: str = "妹") -> None:
        cur = self._cursor_at_end()
        self._maybe_new_block(cur)
        cur.insertText(f"{display_prefix} · ", _bold_format(COLOR_ASST_PREFIX))
        # leave cursor at end with the plain-asst format so streamed chunks inherit it
        cur.setCharFormat(_plain_format(COLOR_ASST_TEXT))
        self.output.setTextCursor(cur)
        self._scroll_to_bottom()

    def stream_chunk(self, delta: str) -> None:
        cur = self._cursor_at_end()
        cur.insertText(delta, _plain_format(COLOR_ASST_TEXT))
        self.output.setTextCursor(cur)
        self._scroll_to_bottom()

    def show_system_note(self, text: str) -> None:
        cur = self._cursor_at_end()
        self._maybe_new_block(cur)
        cur.insertText(text, _plain_format(COLOR_SYS_NOTE, italic=True))
        self.output.setTextCursor(cur)
        self._scroll_to_bottom()

    def clear(self) -> None:
        self.output.clear()


class CompanionWindow(QMainWindow):
    """Frameless transparent always-on-top window with Live2D + chat panel."""

    def __init__(self, cfg: dict, session: ChatSession | None = None) -> None:
        super().__init__()
        self.cfg = cfg
        self.session = session

        w = cfg["app"]["window"]
        self.resize(w.get("width", 460), w.get("height", 760))

        flags = Qt.WindowType.Window
        if w.get("frameless", True):
            flags |= Qt.WindowType.FramelessWindowHint
        if w.get("always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

        if w.get("transparent", True):
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Load per-model sidecar (emotion map, fit mode, paths)
        self.live2d_cfg = Live2DConfig.from_app_config(cfg)

        self.view = QWebEngineView(self)
        self.view.page().setBackgroundColor(Qt.GlobalColor.transparent)
        view_settings = self.view.settings()
        view_settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
        view_settings.setAttribute(
            QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True
        )
        html_path = Path(__file__).resolve().parent.parent / "live2d" / "index.html"
        url = QUrl.fromLocalFile(str(html_path))
        decay_ms = int(self.live2d_cfg.expression_decay_seconds * 1000)
        url.setQuery(
            f"model={self.live2d_cfg.model_url_path}"
            f"&fit={self.live2d_cfg.fit_mode}"
            f"&mouth={self.live2d_cfg.lip_sync_param}"
            f"&decay={decay_ms}"
        )
        self.view.load(url)

        self.chat = ChatPanel(self)
        self.chat.user_message.connect(self._on_user_message)
        self.chat.screenshot_requested.connect(self._on_screenshot)

        # Lazy-init perception
        self._capture = None
        self.observer = None
        self._chat_busy = False
        self.speaker: Speaker | None = None

        self.title_bar = TitleBar(self)
        self.title_bar.settings_clicked.connect(self._on_settings)
        self.title_bar.close_clicked.connect(self.close)
        self.title_bar.proactive_toggled.connect(self._on_eye_toggled)

        central = QWidget(self)
        central.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.title_bar, 0)   # fixed-height drag handle
        layout.addWidget(self.view, 5)
        layout.addWidget(self.chat, 4)
        self.setCentralWidget(central)

        if session is not None:
            backend = session.router.select(session.intent)
            self.chat.show_system_note(
                f"backend: {backend.model}  ·  session: {session.session_id}"
            )
            self._init_observer(cfg)
            self._init_voice(cfg)
            self._check_live2d_model(self.live2d_cfg)
            # First-run guidance: if the default chat backend has no API key,
            # chat will silently 401 on first message. Pop a one-shot dialog
            # right after the window paints and offer to open the model tab.
            QTimer.singleShot(800, self._check_required_api_keys)
        else:
            self.chat.show_system_note("no session bound — chat disabled")
            self.chat.set_input_enabled(False)

    def _check_live2d_model(self, live2d_cfg) -> None:
        """First-run UX: if no Live2D model is on disk, walk the user through
        downloading one from Live2D's official sample page and installing it
        from the zip. We never bundle or auto-download (the Free Material
        License's redistribution clause makes that murky); the user pulls the
        file themselves and we just unpack + wire it up."""
        model_file = live2d_cfg.model_dir / live2d_cfg.model_file
        if model_file.is_file():
            return
        # Defer one tick so the chat panel exists and the user sees the window
        # paint first; otherwise the modal lands on a blank screen.
        QTimer.singleShot(400, self._show_live2d_install_wizard)

    def _show_live2d_install_wizard(self) -> None:
        from PySide6.QtCore import QUrl as _QUrl
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle("没有 Live2D 模型")
        box.setText(
            "她还没有形象。从 Live2D 官方下载一个免费 sample 模型，"
            "然后选择那个 zip 文件就能装上。"
        )
        box.setInformativeText(
            "提示：Live2D 官方 sample 对小型用途免费"
            "（年收入 < 1000 万日元的个人/小公司可商用）。"
            "\n聊天功能即使没有形象也能用。"
        )
        open_site_btn = box.addButton(
            "打开 Live2D 下载页", QMessageBox.ButtonRole.ActionRole
        )
        pick_zip_btn = box.addButton(
            "选择已下载的 zip", QMessageBox.ButtonRole.AcceptRole
        )
        box.addButton("以后再说", QMessageBox.ButtonRole.RejectRole)
        box.exec()

        clicked = box.clickedButton()
        if clicked is open_site_btn:
            QDesktopServices.openUrl(_QUrl("https://www.live2d.com/en/learn/sample/"))
            # Re-show the wizard so the user can come back after downloading.
            QTimer.singleShot(500, self._show_live2d_install_wizard)
            return
        if clicked is not pick_zip_btn:
            return

        zip_str, _ = QFileDialog.getOpenFileName(
            self, "选择 Live2D 模型 zip", "", "Zip 文件 (*.zip)"
        )
        if not zip_str:
            return
        self._install_live2d_zip(Path(zip_str))

    def _install_live2d_zip(self, zip_path: Path) -> None:
        from PySide6.QtWidgets import QMessageBox

        from core import preferences
        from core.live2d_installer import InstallError, install_zip

        try:
            result = install_zip(zip_path)
        except InstallError as e:
            QMessageBox.warning(self, "安装失败", str(e))
            return
        except Exception as e:
            logger.exception("live2d install failed")
            QMessageBox.warning(self, "安装失败", f"{type(e).__name__}: {e}")
            return

        preferences.set_live2d_active_model(result.name)
        self.chat.show_system_note(
            f"已安装 Live2D 模型「{result.name}」"
            f"（{result.expressions} 个表情）。重启 app 让她出现。"
        )
        # Offer to restart so the WebView reloads with the new model URL.
        box = QMessageBox(self)
        box.setWindowTitle("安装完成")
        box.setText(f"已安装「{result.name}」。需要重启 app 才能看到她。")
        restart_btn = box.addButton("现在重启", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("稍后", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is restart_btn:
            import os as _os
            import sys as _sys

            from PySide6.QtWidgets import QApplication

            QApplication.quit()
            # Best-effort relaunch with the same args.
            _os.execv(_sys.executable, [_sys.executable, *_sys.argv])

    def _init_voice(self, cfg: dict) -> None:
        vcfg = cfg.get("voice") or {}
        if not vcfg.get("enabled", False):
            self.title_bar.set_status("· TTS: off", "rgba(180, 180, 180, 150)")
            return
        try:
            backend = TTSBackend.from_config(cfg)
        except Exception as e:
            logger.warning("voice backend init failed, voice disabled: {}", e)
            self.title_bar.set_status("· TTS: init failed", "rgba(255, 120, 120, 200)")
            return
        self.speaker = Speaker(
            backend,
            on_mouth=self._on_voice_mouth,
            audio_device=self._resolve_saved_audio_device(),
        )
        self.speaker.start()
        backend_name = vcfg.get("backend", "edge-tts")
        self.chat.show_system_note(f"语音已启用（{backend_name}）")

        # For gpt-sovits: poll the server health and reflect it in the title bar.
        # edge-tts has no server to check; just show "ready".
        if backend_name == "gpt-sovits":
            sovits_url = (vcfg.get("sovits") or {}).get("base_url", "http://127.0.0.1:9880")
            self._tts_ping_url = f"{sovits_url.rstrip('/')}/control?command=ping"
            self._tts_ping_timer = QTimer(self)
            self._tts_ping_timer.timeout.connect(self._ping_tts_server)
            self._tts_ping_timer.start(5000)
            self._ping_tts_server()  # immediate first check
        else:
            self.title_bar.set_status(
                f"· TTS: {backend_name}", "rgba(160, 220, 160, 200)"
            )

    def _ping_tts_server(self) -> None:
        """Quick non-blocking health check of the GPT-SoVITS server."""
        import httpx

        url = getattr(self, "_tts_ping_url", None)
        if not url:
            return
        try:
            r = httpx.get(url, timeout=1.5)
            if r.status_code == 200:
                self.title_bar.set_status(
                    "· TTS: ✓ ready", "rgba(160, 220, 160, 200)"
                )
            else:
                self.title_bar.set_status(
                    f"· TTS: HTTP {r.status_code}", "rgba(255, 200, 120, 220)"
                )
        except Exception:
            self.title_bar.set_status(
                "· TTS: ✗ offline", "rgba(255, 120, 120, 220)"
            )

    def _on_voice_mouth(self, value: float) -> None:
        """Speaker callback: drive Live2D mouth open via JS."""
        js = f"if(window.imouto) window.imouto.setMouthOpen({value:.3f});"
        self.view.page().runJavaScript(js)

    def _check_required_api_keys(self) -> None:
        """If the active chat backend has no API key configured, surface a
        dialog and offer to open the model tab. Runs once at startup; can
        be retriggered after user action by calling this again."""
        if self.session is None or self.session.router is None:
            return
        backend = self.session.router.select(self.session.intent)
        # OpenAICompatBackend stores api_key as "" when missing (see
        # core/brain/openai_compat.py). Treat both empty and unset as missing.
        has_key = bool(getattr(backend, "api_key", "") or "")
        if has_key:
            return

        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle("需要 API 密钥")
        box.setText(
            f"当前默认后端 <b>{backend.name}</b>（{backend.model}）没有 API 密钥，"
            "聊天会请求失败。"
        )
        box.setInformativeText("现在打开设置去填写吗？")
        open_btn = box.addButton("打开设置", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("以后再说", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            self._on_settings()

    def _resolve_saved_audio_device(self):
        """Look up the saved audio output device by id (or None for default)."""
        from PySide6.QtMultimedia import QMediaDevices

        from core import preferences

        saved = preferences.get_audio_output_id()
        if not saved:
            return None
        for dev in QMediaDevices.audioOutputs():
            try:
                if bytes(dev.id()).hex() == saved:
                    logger.info("audio output: using saved device '{}'", dev.description())
                    return dev
            except Exception:
                continue
        logger.warning("audio output: saved device id not found, using system default")
        return None

    def _init_observer(self, cfg: dict) -> None:
        from core.perception import Capture, PrivacyGuard, ProactiveObserver

        pcfg = (cfg.get("perception", {}) or {}).get("proactive", {}) or {}
        if not pcfg:
            return
        # Eagerly create capture so observer + manual share the same instance.
        # Privacy guard is shared too — the title bar polls it for the red
        # indicator, manual screenshot path gates on it, and observer aborts
        # an eval if the foreground window matches.
        self._capture = Capture(max_edge=1024)
        self.privacy_guard = PrivacyGuard.from_config(cfg)
        self.observer = ProactiveObserver(
            session=self.session,
            capture=self._capture,
            on_speak=self._on_proactive_speak,
            enabled=pcfg.get("enabled", True),
            timer_seconds=pcfg.get("timer_seconds", 600),
            cooldown_seconds=pcfg.get("cooldown_seconds", 600),
            min_silence_after_user=pcfg.get("min_silence_after_user", 30),
            window_switch_enabled=pcfg.get("window_switch_enabled", True),
            idle_threshold_seconds=pcfg.get("idle_threshold_seconds", 600),
            poll_interval=pcfg.get("poll_interval", 5.0),
            is_busy=lambda: self._chat_busy,
            privacy=self.privacy_guard,
        )
        self.observer.start()
        # Title bar red indicator: poll the foreground window every 2 s and
        # toggle the visual lock-icon. 2 s is the right tradeoff: fast enough
        # to feel reactive when alt-tabbing to 1Password, slow enough to be
        # negligible CPU (one GetWindowText call).
        self._privacy_active = False
        self._privacy_timer = QTimer(self)
        self._privacy_timer.timeout.connect(self._poll_privacy_state)
        self._privacy_timer.start(2000)
        self._poll_privacy_state()
        if self.observer.is_enabled():
            self.chat.show_system_note(
                f"主动模式已启用（每 {int(self.observer.timer_seconds // 60)} 分钟评估，"
                f"间隔不少于 {int(self.observer.cooldown_seconds // 60)} 分钟）"
            )

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw a thin semi-transparent rounded border so users can see
        where the frameless transparent window actually ends. Without this,
        clicking the transparent Live2D area looks identical to clicking
        the desktop behind it."""
        super().paintEvent(event)
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(255, 182, 217, 110))  # soft pink, ~43% alpha
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            inset = 1
            rect = QRectF(
                inset, inset, self.width() - inset * 2, self.height() - inset * 2
            )
            painter.drawRoundedRect(rect, 12, 12)
        finally:
            painter.end()

    def _on_user_message(self, text: str) -> None:
        if self.session is None:
            return
        asyncio.ensure_future(self._handle_chat(text))

    def _on_screenshot(self, text: str = "") -> None:
        if self.session is None:
            return
        # Manual screenshot also respects the privacy guard — same blocklist
        # that gates proactive evals, but here we surface the rejection
        # directly in the chat panel so the user understands why nothing
        # was sent.
        guard = getattr(self, "privacy_guard", None)
        if guard is not None:
            blocked, matched = guard.check_active_window()
            if blocked:
                self.chat.show_system_note(
                    f"🔒 隐私拦截：前台窗口「{matched}」命中黑名单，截屏未发送。"
                )
                return
        asyncio.ensure_future(self._handle_screenshot(text))

    def _on_eye_toggled(self, can_see: bool) -> None:
        """Title-bar eye toggle: stop / resume proactive screen evaluation.
        Manual screenshot still works (user-initiated); this only gates the
        observer's autonomous screen peeks."""
        if self.observer is not None:
            self.observer.set_enabled(can_see)
        note = "👁 已恢复主动观察" if can_see else "🙈 已暂停主动观察（手动截屏不受影响）"
        self.chat.show_system_note(note)

    def _poll_privacy_state(self) -> None:
        """Check the foreground window every 2 s and reflect the result in
        the title bar. Idempotent — only updates UI when state changes."""
        guard = getattr(self, "privacy_guard", None)
        if guard is None:
            return
        blocked, matched = guard.check_active_window()
        if blocked == self._privacy_active:
            return
        self._privacy_active = blocked
        self.title_bar.set_privacy_active(blocked, matched)

    def _on_settings(self) -> None:
        from app.settings_dialog import SettingsDialog

        dlg = SettingsDialog(self.cfg, self.session, self)
        dlg.persona_changed.connect(self._on_persona_changed)
        dlg.memory_cleared.connect(self._on_memory_cleared)
        dlg.exec()

    def _on_persona_changed(self) -> None:
        self.chat.show_system_note("人设已更新（下条消息生效）")

    def _on_memory_cleared(self) -> None:
        self.chat.clear()
        self.chat.show_system_note("记忆已清空")

    def _get_capture(self):
        if self._capture is None:
            from core.perception import Capture
            self._capture = Capture(max_edge=1024)
        return self._capture

    def _on_proactive_speak(self, comment: str) -> None:
        """Observer calls this from inside the qasync loop when she decides to talk."""
        if self._chat_busy:
            return
        self._chat_busy = True
        try:
            rest, emotion = self._strip_emotion_prefix(comment)
            self._trigger_emotion(emotion)
            self.chat.begin_assistant(self._display_prefix())
            self.chat.stream_chunk(rest)
            if self.speaker is not None and rest.strip():
                self.speaker.enqueue(rest.strip())
        finally:
            self._chat_busy = False

    @staticmethod
    def _strip_emotion_prefix(text: str) -> tuple[str, str | None]:
        m = EMOTION_TAG_RE.match(text)
        if not m:
            return text, None
        return text[m.end():], m.group(1).strip()

    def _trigger_emotion(self, emotion: str | None) -> None:
        if not emotion:
            return
        expr = self.live2d_cfg.emotion_mapping.get(emotion)
        if expr is None:
            # 平静 / unknown: clear expression
            js = "if(window.imouto) window.imouto.clearExpression();"
        else:
            js = (
                "if(window.imouto) window.imouto.setExpression("
                + json.dumps(expr, ensure_ascii=False)
                + ");"
            )
        self.view.page().runJavaScript(js)

    def _display_prefix(self) -> str:
        if self.session is not None and hasattr(self.session, "persona_display_prefix"):
            return self.session.persona_display_prefix
        return "妹"

    async def _stream_with_emotion(self, chunk_iter) -> None:
        """Consume an async chunk stream; sniff the leading [心情:XX] tag,
        fire the matching expression once, stream the rest into the chat panel,
        and pipe sentences to the Speaker as punctuation arrives."""
        buf = ""
        emotion_handled = False
        sentence_buf = SentenceBuffer() if self.speaker is not None else None

        def emit(text: str) -> None:
            self.chat.stream_chunk(text)
            if sentence_buf is not None and self.speaker is not None:
                for sentence in sentence_buf.feed(text):
                    self.speaker.enqueue(sentence)

        async for chunk in chunk_iter:
            if not emotion_handled:
                buf += chunk.delta
                m = EMOTION_TAG_RE.match(buf)
                if m:
                    self._trigger_emotion(m.group(1).strip())
                    tail = buf[m.end():]
                    emotion_handled = True
                    buf = ""
                    if tail:
                        emit(tail)
                elif len(buf) >= 48:
                    emotion_handled = True
                    emit(buf)
                    buf = ""
            else:
                emit(chunk.delta)

        if not emotion_handled and buf:
            emit(buf)
        # Flush any unspoken tail (no trailing punctuation)
        if sentence_buf is not None and self.speaker is not None:
            leftover = sentence_buf.flush()
            if leftover:
                self.speaker.enqueue(leftover)

    async def _handle_chat(self, text: str) -> None:
        assert self.session is not None
        self._chat_busy = True
        if self.observer is not None:
            self.observer.notify_user_spoke()
        self.chat.set_input_enabled(False)
        self.chat.begin_user(text)
        self.chat.begin_assistant(self._display_prefix())
        try:
            await self._stream_with_emotion(self.session.chat(text))
        except Exception as e:
            self.chat.show_system_note(f"error: {e}")
        finally:
            self.chat.set_input_enabled(True)
            self._chat_busy = False

    async def _handle_screenshot(self, text: str = "") -> None:
        assert self.session is not None
        self._chat_busy = True
        if self.observer is not None:
            self.observer.notify_user_spoke()
        self.chat.set_input_enabled(False)
        display = f"📷 {text}" if text else "📷 (截屏)"
        self.chat.begin_user(display)
        self.chat.begin_assistant(self._display_prefix())
        try:
            capture = self._get_capture()
            await self._stream_with_emotion(
                self.session.see_screen(capture, user_text=text or None)
            )
        except Exception as e:
            self.chat.show_system_note(f"screenshot error: {e}")
        finally:
            self.chat.set_input_enabled(True)
            self._chat_busy = False

    def closeEvent(self, event) -> None:
        if self.observer is not None:
            self.observer.stop()
        if self.speaker is not None:
            self.speaker.stop()
        super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.chat.input.clear()
            return
        if (
            event.modifiers() == Qt.KeyboardModifier.ControlModifier
            and event.key() == Qt.Key.Key_Q
        ):
            self.close()
            return
        super().keyPressEvent(event)
