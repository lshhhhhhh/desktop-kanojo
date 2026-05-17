from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.persona import Persona

if TYPE_CHECKING:
    from core.session import ChatSession


def _format_examples(examples: list[tuple[str, str]]) -> str:
    """Render examples as 'user\\nassistant\\n\\n...' for the textarea."""
    return "\n\n".join(f"{u}\n{a}" for u, a in examples)


def _parse_examples(text: str) -> list[tuple[str, str]]:
    """Parse the textarea: first non-empty line = user, second = assistant.
    Blank lines separate pairs (but we also support continuous alternation)."""
    lines = [ln.rstrip() for ln in text.split("\n") if ln.strip()]
    pairs: list[tuple[str, str]] = []
    for i in range(0, len(lines) - 1, 2):
        pairs.append((lines[i], lines[i + 1]))
    return pairs


DIALOG_STYLE = """
QDialog { background-color: #1e1e2a; color: #f5f0f5; }
QLabel { color: #f5f0f5; }
QLineEdit, QPlainTextEdit, QComboBox, QListWidget {
    background-color: #2a2a38;
    color: #f5f0f5;
    border: 1px solid #444;
    border-radius: 4px;
    padding: 4px;
}
QPushButton {
    background-color: rgba(255, 130, 180, 100);
    color: white;
    border: none;
    border-radius: 4px;
    padding: 6px 14px;
}
QPushButton:hover { background-color: rgba(255, 130, 180, 180); }
QTabBar::tab {
    background: #2a2a38;
    color: #f5f0f5;
    padding: 6px 14px;
    border: 1px solid #444;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}
QTabBar::tab:selected { background: #3a3a4a; }
QTabWidget::pane { border: 1px solid #444; }
"""


class SettingsDialog(QDialog):
    persona_changed = Signal()
    memory_cleared = Signal()
    monitor_changed = Signal(int)
    audio_device_changed = Signal(object)  # emits QAudioDevice or None

    def __init__(
        self,
        cfg: dict,
        session: "ChatSession | None",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setStyleSheet(DIALOG_STYLE)
        self.resize(640, 600)
        self.cfg = cfg
        self.session = session
        self.personas_dir = Path(cfg.get("persona", {}).get("path", "./personas"))

        tabs = QTabWidget(self)
        tabs.addTab(self._build_model_tab(), "模型")
        tabs.addTab(self._build_persona_tab(), "人设")
        tabs.addTab(self._build_proactive_tab(), "主动")
        tabs.addTab(self._build_memory_tab(), "记忆")
        tabs.addTab(self._build_screen_tab(), "屏幕")
        tabs.addTab(self._build_voice_tab(), "语音")

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    # ---------------------------------------------------------------- persona

    def _build_persona_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        row = QHBoxLayout()
        row.addWidget(QLabel("人设："))
        self.persona_combo = QComboBox()
        self._reload_persona_list()
        self.persona_combo.currentTextChanged.connect(self._on_persona_selected)
        row.addWidget(self.persona_combo, 1)

        new_btn = QPushButton("新建")
        new_btn.clicked.connect(self._on_new_persona)
        row.addWidget(new_btn)
        layout.addLayout(row)

        form = QFormLayout()
        self.name_input = QLineEdit()
        self.prefix_input = QLineEdit()
        self.prefix_input.setMaxLength(4)
        form.addRow("名字：", self.name_input)
        form.addRow("聊天前缀：", self.prefix_input)
        layout.addLayout(form)

        layout.addWidget(QLabel("系统提示词："))
        self.system_prompt_edit = QPlainTextEdit()
        self.system_prompt_edit.setMinimumHeight(140)
        layout.addWidget(self.system_prompt_edit, 2)

        layout.addWidget(QLabel("示范对话（一行用户、一行助手，空行分隔）："))
        self.examples_edit = QPlainTextEdit()
        self.examples_edit.setMinimumHeight(120)
        layout.addWidget(self.examples_edit, 2)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("保存到文件")
        save_btn.clicked.connect(self._save_persona_to_file)
        apply_btn = QPushButton("保存并应用")
        apply_btn.clicked.connect(self._apply_persona)
        btn_row.addStretch(1)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(apply_btn)
        layout.addLayout(btn_row)

        # Populate from current
        if self.session is not None:
            self._load_persona_into_ui(self.session.persona_obj)
        return w

    def _reload_persona_list(self) -> None:
        self.persona_combo.blockSignals(True)
        self.persona_combo.clear()
        names = Persona.list_available(self.personas_dir)
        if not names:
            names = ["default"]
        self.persona_combo.addItems(names)
        current = self.cfg.get("persona", {}).get("active", "default")
        if current in names:
            self.persona_combo.setCurrentText(current)
        self.persona_combo.blockSignals(False)

    def _on_persona_selected(self, name: str) -> None:
        path = self.personas_dir / f"{name}.yaml"
        if not path.exists():
            return
        try:
            p = Persona.from_file(path)
            self._load_persona_into_ui(p)
        except Exception as e:
            QMessageBox.warning(self, "加载失败", str(e))

    def _load_persona_into_ui(self, p: Persona) -> None:
        # Track the loaded name so we can auto-rename references on save.
        self._original_name = p.name
        self.name_input.setText(p.name)
        self.prefix_input.setText(p.display_prefix)
        self.system_prompt_edit.setPlainText(p.system_prompt)
        self.examples_edit.setPlainText(_format_examples(p.examples))

    def _persona_from_ui(self) -> Persona:
        return Persona(
            name=self.name_input.text().strip() or "小妹",
            display_prefix=self.prefix_input.text().strip() or "妹",
            system_prompt=self.system_prompt_edit.toPlainText().strip(),
            examples=_parse_examples(self.examples_edit.toPlainText()),
        )

    def _autorename(self, p: Persona) -> tuple[Persona, int]:
        """If name changed since load, replace old name in prompt + examples."""
        old = getattr(self, "_original_name", None)
        if not old or old == p.name or len(old) < 1:
            return p, 0
        count = p.system_prompt.count(old)
        new_prompt = p.system_prompt.replace(old, p.name)
        new_examples: list[tuple[str, str]] = []
        for u, a in p.examples:
            count += u.count(old) + a.count(old)
            new_examples.append((u.replace(old, p.name), a.replace(old, p.name)))
        renamed = Persona(
            name=p.name,
            display_prefix=p.display_prefix,
            system_prompt=new_prompt,
            examples=new_examples,
        )
        return renamed, count

    def _save_persona_to_file(self) -> None:
        try:
            p = self._persona_from_ui()
            p, renamed = self._autorename(p)
            if renamed:
                self._load_persona_into_ui(p)  # reflect rename in UI
            stem = self.persona_combo.currentText() or "default"
            target = self.personas_dir / f"{stem}.yaml"
            p.save(target)
            msg = f"写入 {target}"
            if renamed:
                msg += f"\n自动替换了 {renamed} 处旧名字"
            QMessageBox.information(self, "已保存", msg)
            self._reload_persona_list()
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))

    def _apply_persona(self) -> None:
        try:
            p = self._persona_from_ui()
            p, renamed = self._autorename(p)
            if renamed:
                self._load_persona_into_ui(p)
            stem = self.persona_combo.currentText() or "default"
            target = self.personas_dir / f"{stem}.yaml"
            p.save(target)
            if self.session is not None:
                self.session.set_persona(p)
            self.persona_changed.emit()
            msg = "下条消息生效。"
            if renamed:
                msg = f"自动替换了 {renamed} 处旧名字。\n{msg}"
            QMessageBox.information(self, "已应用", msg)
        except Exception as e:
            QMessageBox.warning(self, "应用失败", str(e))

    def _on_new_persona(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "新建人设", "文件名（不含 .yaml）：")
        if not ok or not name.strip():
            return
        stem = "".join(c for c in name.strip() if c.isalnum() or c in "-_") or name.strip()
        target = self.personas_dir / f"{stem}.yaml"
        if target.exists():
            QMessageBox.warning(self, "已存在", f"{target} 已存在")
            return
        p = self._persona_from_ui()
        p.save(target)
        self._reload_persona_list()
        self.persona_combo.setCurrentText(stem)

    # ---------------------------------------------------------------- memory

    def _build_memory_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        self.memory_stats_label = QLabel()
        layout.addWidget(self.memory_stats_label)

        layout.addWidget(QLabel("已记住的事实："))
        self.facts_list = QListWidget()
        layout.addWidget(self.facts_list, 1)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._refresh_memory_view)
        btn_row.addWidget(refresh_btn)
        btn_row.addStretch(1)
        clear_btn = QPushButton("清空所有记忆")
        clear_btn.setStyleSheet(
            "QPushButton { background-color: rgba(220, 80, 80, 200); }"
            "QPushButton:hover { background-color: rgba(255, 60, 60, 240); }"
        )
        clear_btn.clicked.connect(self._clear_memory)
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

        self._refresh_memory_view()
        return w

    def _refresh_memory_view(self) -> None:
        if self.session is None:
            self.memory_stats_label.setText("无会话")
            self.facts_list.clear()
            return
        ep_count = self.session.memory.episodic.count()
        facts = self.session.memory.facts.all_active()
        self.memory_stats_label.setText(
            f"对话片段：{ep_count} 条    ·    提炼事实：{len(facts)} 条"
        )
        self.facts_list.clear()
        for f in facts:
            item = QListWidgetItem(
                f"{f.key}：{f.value}    (confidence={f.confidence:.2f})"
            )
            self.facts_list.addItem(item)

    def _clear_memory(self) -> None:
        reply = QMessageBox.warning(
            self,
            "确认清空",
            "确定要清空所有记忆吗？\n包括对话片段、提炼事实、截屏观察。\n此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self.session is None:
            return
        conn = self.session.memory.conn
        for table in (
            "episodes",
            "episodes_vec",
            "facts",
            "screen_obs",
            "screen_obs_vec",
            "meta",
        ):
            try:
                conn.execute(f"DELETE FROM {table}")
            except Exception as e:
                logger.warning("failed to clear {}: {}", table, e)
        conn.commit()
        self.session.memory.working.clear()
        self.session.memory._turns_since_reflection = 0
        self.session.memory._last_reflected_episode_id = 0
        self._refresh_memory_view()
        self.memory_cleared.emit()

    # ---------------------------------------------------------------- screen

    def _build_screen_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel("截屏来源（多屏可选择拼接全部或单屏）："))
        self.monitor_combo = QComboBox()
        try:
            from core.perception import Capture

            mons = Capture().list_monitors()
            self.monitor_combo.addItem("全部屏幕（拼接）", 0)
            for i in range(1, len(mons)):
                m = mons[i]
                self.monitor_combo.addItem(
                    f"屏幕 {i}    ·    {m['width']}×{m['height']}    "
                    f"(左上角 {m['left']},{m['top']})",
                    i,
                )
        except Exception as e:
            self.monitor_combo.addItem(f"加载失败：{e}", 0)

        current = 0
        parent = self.parent()
        if parent is not None and hasattr(parent, "_capture") and parent._capture is not None:
            current = parent._capture.monitor_index
        for i in range(self.monitor_combo.count()):
            if self.monitor_combo.itemData(i) == current:
                self.monitor_combo.setCurrentIndex(i)
                break

        layout.addWidget(self.monitor_combo)

        apply_btn = QPushButton("应用")
        apply_btn.clicked.connect(self._apply_screen)
        layout.addWidget(apply_btn)

        layout.addStretch(1)
        return w

    def _apply_screen(self) -> None:
        idx = self.monitor_combo.currentData()
        if idx is None:
            return
        parent = self.parent()
        if parent is not None and hasattr(parent, "_get_capture"):
            cap = parent._get_capture()
            cap.monitor_index = int(idx)
            self.monitor_changed.emit(int(idx))
            QMessageBox.information(self, "已应用", f"下次截屏使用源：{idx}")

    # ---------------------------------------------------------------- voice

    def _build_voice_tab(self) -> QWidget:
        from PySide6.QtMultimedia import QMediaDevices

        from core import preferences

        w = QWidget()
        layout = QVBoxLayout(w)

        layout.addWidget(QLabel("音频输出设备："))
        self.audio_combo = QComboBox()

        # First item = system default (passing None to QAudioSink uses it)
        default_dev = QMediaDevices.defaultAudioOutput()
        default_desc = default_dev.description() if default_dev is not None else "?"
        self.audio_combo.addItem(f"系统默认（{default_desc}）", None)

        outputs = QMediaDevices.audioOutputs()
        for dev in outputs:
            self.audio_combo.addItem(dev.description(), dev)

        # Preselect the active device. Prefer the live Speaker setting, falling
        # back to whatever is saved in preferences.
        active_id_hex: str | None = None
        parent = self.parent()
        if parent is not None and getattr(parent, "speaker", None) is not None:
            d = getattr(parent.speaker, "_audio_device", None)
            if d is not None:
                try:
                    active_id_hex = bytes(d.id()).hex()
                except Exception:
                    active_id_hex = None
        if active_id_hex is None:
            active_id_hex = preferences.get_audio_output_id()
        if active_id_hex:
            for i in range(1, self.audio_combo.count()):
                d = self.audio_combo.itemData(i)
                try:
                    if bytes(d.id()).hex() == active_id_hex:
                        self.audio_combo.setCurrentIndex(i)
                        break
                except Exception:
                    continue

        layout.addWidget(self.audio_combo)

        btn_row = QHBoxLayout()
        test_btn = QPushButton("试听")
        test_btn.clicked.connect(self._test_audio_device)
        apply_btn = QPushButton("应用并保存")
        apply_btn.clicked.connect(self._apply_audio_device)
        btn_row.addWidget(test_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(apply_btn)
        layout.addLayout(btn_row)

        self.voice_status = QLabel("")
        self.voice_status.setStyleSheet("color: #aaa;")
        layout.addWidget(self.voice_status)

        layout.addStretch(1)
        return w

    def _selected_audio_device(self):
        """Returns the QAudioDevice for the current combo selection, or
        None for "system default"."""
        return self.audio_combo.itemData(self.audio_combo.currentIndex())

    def _test_audio_device(self) -> None:
        """Play a short tone through the currently-selected device so the user
        can confirm it's the right one before applying."""
        import math
        import struct

        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtMultimedia import QAudioFormat, QAudioSink

        dev = self._selected_audio_device()
        sr = 48000
        duration = 0.6
        n = int(sr * duration)
        frames = bytearray()
        for i in range(n):
            # gentle fade in/out so it doesn't click
            env = min(1.0, i / (sr * 0.05), (n - i) / (sr * 0.05))
            v = int(0.25 * env * 32767 * math.sin(2 * math.pi * 660 * i / sr))
            frames += struct.pack("<h", v)

        fmt = QAudioFormat()
        fmt.setSampleRate(sr)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.Int16)
        sink = QAudioSink(dev, fmt) if dev is not None else QAudioSink(fmt)
        # Keep a reference on self so it isn't GC'd before playback finishes.
        self._test_sink = sink
        self._test_buf = QBuffer()
        self._test_buf.setData(QByteArray(bytes(frames)))
        self._test_buf.open(QIODevice.ReadOnly)
        sink.start(self._test_buf)
        self.voice_status.setText("试听中…")

    def _apply_audio_device(self) -> None:
        from core import preferences

        dev = self._selected_audio_device()
        parent = self.parent()
        if parent is not None and getattr(parent, "speaker", None) is not None:
            parent.speaker.set_audio_device(dev)
        try:
            dev_id_hex = bytes(dev.id()).hex() if dev is not None else None
        except Exception:
            dev_id_hex = None
        preferences.set_audio_output_id(dev_id_hex)
        self.audio_device_changed.emit(dev)
        name = dev.description() if dev is not None else "系统默认"
        self.voice_status.setText(f"已设为：{name}（下一句生效）")

    # ---------------------------------------------------------------- proactive

    def _get_observer(self):
        parent = self.parent()
        if parent is None or not hasattr(parent, "observer"):
            return None
        return parent.observer

    def _build_proactive_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        observer = self._get_observer()
        if observer is None:
            layout.addWidget(QLabel("主动模式不可用（无会话）"))
            layout.addStretch(1)
            return w

        layout.addWidget(QLabel(
            "她会按下面的节奏在后台偷瞄屏幕，判断要不要主动说话。\n"
            "评估走便宜的视觉模型，多数时候静默——只有判断"
            "「值得开口」时才在聊天框冒泡。"
        ))

        self.proactive_enabled = QCheckBox("启用主动聊天")
        self.proactive_enabled.setChecked(observer.is_enabled())
        self.proactive_enabled.toggled.connect(observer.set_enabled)
        self.proactive_enabled.toggled.connect(lambda _: self._refresh_proactive_status())
        layout.addWidget(self.proactive_enabled)

        form = QFormLayout()

        self.timer_spin = QSpinBox()
        self.timer_spin.setRange(1, 240)
        self.timer_spin.setSuffix(" 分钟")
        self.timer_spin.setValue(max(1, int(observer.timer_seconds // 60)))
        self.timer_spin.valueChanged.connect(
            lambda v: setattr(observer, "timer_seconds", v * 60)
        )
        form.addRow("检查间隔：", self.timer_spin)

        self.cooldown_spin = QSpinBox()
        self.cooldown_spin.setRange(1, 240)
        self.cooldown_spin.setSuffix(" 分钟")
        self.cooldown_spin.setValue(max(1, int(observer.cooldown_seconds // 60)))
        self.cooldown_spin.valueChanged.connect(
            lambda v: setattr(observer, "cooldown_seconds", v * 60)
        )
        form.addRow("最短发言间隔：", self.cooldown_spin)

        self.idle_spin = QSpinBox()
        self.idle_spin.setRange(1, 240)
        self.idle_spin.setSuffix(" 分钟")
        self.idle_spin.setValue(max(1, int(observer.idle_threshold_seconds // 60)))
        self.idle_spin.valueChanged.connect(
            lambda v: setattr(observer, "idle_threshold_seconds", v * 60)
        )
        form.addRow("空闲多久算闲：", self.idle_spin)

        layout.addLayout(form)

        self.window_switch_check = QCheckBox("窗口切换时也评估")
        self.window_switch_check.setChecked(observer.window_switch_enabled)
        self.window_switch_check.toggled.connect(
            lambda on: setattr(observer, "window_switch_enabled", on)
        )
        layout.addWidget(self.window_switch_check)

        self.proactive_status_label = QLabel()
        self._refresh_proactive_status()
        layout.addWidget(self.proactive_status_label)

        refresh_btn = QPushButton("刷新状态")
        refresh_btn.clicked.connect(self._refresh_proactive_status)
        layout.addWidget(refresh_btn)

        layout.addStretch(1)
        return w

    def _refresh_proactive_status(self) -> None:
        obs = self._get_observer()
        if obs is None or not hasattr(self, "proactive_status_label"):
            return
        self.proactive_status_label.setText(f"状态：{obs.status_text()}")

    # ---------------------------------------------------------------- model

    def _build_model_tab(self) -> QWidget:
        from core import env_file, preferences

        w = QWidget()
        layout = QVBoxLayout(w)

        # --- API keys ---
        layout.addWidget(QLabel("API 密钥"))
        key_box = QFormLayout()
        self._key_inputs: dict[str, QLineEdit] = {}
        self._key_status: dict[str, QLabel] = {}

        required = env_file.collect_required_env_keys(self.cfg)
        if not required:
            key_box.addRow(QLabel("（config 中没有引用任何 api_key_env）"))

        import os

        for env_name in required:
            row = QHBoxLayout()
            status = QLabel()
            status.setMinimumWidth(80)
            self._key_status[env_name] = status

            edit = QLineEdit()
            edit.setEchoMode(QLineEdit.Password)
            # Prefill with the currently-effective value (env > .env) so the
            # user can see what's there, edit it, and rotate without having
            # to dig the key out of the source again.
            current = os.environ.get(env_name) or env_file.read_env_value(env_name) or ""
            if current:
                edit.setText(current)
            else:
                edit.setPlaceholderText("（粘贴 key）")
            self._key_inputs[env_name] = edit

            reveal_btn = QPushButton("显示")
            reveal_btn.setCheckable(True)
            reveal_btn.setFixedWidth(56)
            reveal_btn.toggled.connect(
                lambda checked, e=edit, b=reveal_btn: (
                    e.setEchoMode(
                        QLineEdit.Normal if checked else QLineEdit.Password
                    ),
                    b.setText("隐藏" if checked else "显示"),
                )
            )

            save_btn = QPushButton("保存")
            save_btn.clicked.connect(lambda _=False, n=env_name: self._save_api_key(n))

            row.addWidget(status)
            row.addWidget(edit, 1)
            row.addWidget(reveal_btn)
            row.addWidget(save_btn)
            row_w = QWidget()
            row_w.setLayout(row)
            key_box.addRow(env_name + "：", row_w)
            self._refresh_key_status(env_name)

        layout.addLayout(key_box)
        hint = QLabel(
            "密钥保存到 .env 文件，并立即注入当前进程。"
            "\n注意：已构造的后端缓存了旧密钥；切换后端或重启才能完全生效。"
        )
        hint.setStyleSheet("color: #aaa;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # --- default chat backend ---
        layout.addSpacing(12)
        layout.addWidget(QLabel("默认聊天后端"))
        backend_row = QHBoxLayout()
        self.backend_combo = QComboBox()
        router = self.session.router if self.session is not None else None
        names = list(router.backends.keys()) if router else []
        for name in names:
            be = router.backends[name] if router else None
            label = name
            if be is not None:
                label = f"{name}   ·   {be.model}"
            self.backend_combo.addItem(label, name)
        current = preferences.get_chat_backend() or (router.default if router else None)
        if current:
            for i in range(self.backend_combo.count()):
                if self.backend_combo.itemData(i) == current:
                    self.backend_combo.setCurrentIndex(i)
                    break
        backend_row.addWidget(self.backend_combo, 1)

        apply_backend_btn = QPushButton("应用")
        apply_backend_btn.clicked.connect(self._apply_chat_backend)
        backend_row.addWidget(apply_backend_btn)
        layout.addLayout(backend_row)

        # --- connectivity test ---
        test_row = QHBoxLayout()
        test_btn = QPushButton("测试连通")
        test_btn.clicked.connect(self._test_chat_backend)
        test_row.addWidget(test_btn)
        test_row.addStretch(1)
        layout.addLayout(test_row)

        self.model_status = QLabel("")
        self.model_status.setStyleSheet("color: #aaa;")
        self.model_status.setWordWrap(True)
        layout.addWidget(self.model_status)

        layout.addStretch(1)
        return w

    def _refresh_key_status(self, env_name: str) -> None:
        from core import env_file

        label = self._key_status.get(env_name)
        if label is None:
            return
        if env_file.has_env_value(env_name):
            label.setText("● 已设置")
            label.setStyleSheet("color: #6cc070;")
        else:
            label.setText("○ 未设置")
            label.setStyleSheet("color: #d07070;")

    def _save_api_key(self, env_name: str) -> None:
        import os

        from core import env_file

        edit = self._key_inputs.get(env_name)
        if edit is None:
            return
        value = edit.text().strip()
        if not value:
            QMessageBox.information(self, "无变化", "输入框为空，未做更改。")
            return
        # No-op if unchanged — avoids touching .env when the user just
        # opened the dialog and clicked save without editing.
        if value == (os.environ.get(env_name) or env_file.read_env_value(env_name) or ""):
            QMessageBox.information(self, "无变化", "与已保存的值相同。")
            return
        try:
            env_file.upsert_env_value(env_name, value)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return
        self._refresh_key_status(env_name)
        QMessageBox.information(
            self,
            "已保存",
            f"{env_name} 已写入 .env。\n切换后端或重启 app 让所有路径生效。",
        )

    def _apply_chat_backend(self) -> None:
        from core import preferences

        name = self.backend_combo.currentData()
        if not name:
            return
        if self.session is not None and self.session.router is not None:
            if name not in self.session.router.backends:
                QMessageBox.warning(self, "未知后端", f"后端 {name!r} 不在 router 中。")
                return
            self.session.router.default = name
        preferences.set_chat_backend(name)
        self.model_status.setText(
            f"已切换默认后端为：{name}（已保存，下次启动自动生效）"
        )

    def _test_chat_backend(self) -> None:
        """Fire a tiny round-trip against the currently-selected backend.
        Picks up env var changes from this session (the backend object itself
        cached its api_key at construction, so newly-saved keys won't take
        effect here — that's why the hint above mentions a restart)."""
        import asyncio

        from core.brain.base import ChatRequest, ContentPart, Message

        if self.session is None or self.session.router is None:
            self.model_status.setText("无 session，无法测试。")
            return
        name = self.backend_combo.currentData()
        backend = self.session.router.backends.get(name)
        if backend is None:
            self.model_status.setText(f"未知后端：{name}")
            return

        async def run() -> str:
            req = ChatRequest(
                messages=[Message(role="user", content=[ContentPart(type="text", text="hi")])],
                stream=False,
                max_tokens=8,
            )
            first = ""
            async for chunk in backend.chat(req):
                first += chunk.delta
                if first:
                    break
            return first

        self.model_status.setText(f"测试 {name} ...")
        loop = asyncio.get_event_loop()
        task = asyncio.ensure_future(run())

        def done(t: asyncio.Task) -> None:
            try:
                reply = t.result()
                self.model_status.setText(
                    f"{name}: ✓ 回复：{(reply or '(空)')[:60]}"
                )
            except Exception as e:
                self.model_status.setText(f"{name}: ✗ {type(e).__name__}: {e}")

        task.add_done_callback(done)
