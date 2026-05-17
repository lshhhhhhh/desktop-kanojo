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
        session: ChatSession | None,
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
        self._tabs = tabs
        tabs.addTab(self._build_model_tab(), "模型")
        tabs.addTab(self._build_persona_tab(), "人设")
        tabs.addTab(self._build_proactive_tab(), "主动")
        tabs.addTab(self._build_memory_tab(), "记忆")
        tabs.addTab(self._build_screen_tab(), "屏幕")
        tabs.addTab(self._build_voice_tab(), "语音")
        tabs.addTab(self._build_form_tab(), "形象")

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
        self.user_address_input = QLineEdit()
        self.user_address_input.setMaxLength(16)
        self.user_address_input.setPlaceholderText(
            "如「哥哥」「主人」或你的真名；留空 = 默认「你」"
        )
        form.addRow("名字：", self.name_input)
        form.addRow("聊天前缀：", self.prefix_input)
        form.addRow("她对我的称呼：", self.user_address_input)
        layout.addLayout(form)

        layout.addWidget(QLabel("系统提示词（只写人设描述，不用写角色名/称呼）："))
        self.system_prompt_edit = QPlainTextEdit()
        self.system_prompt_edit.setMinimumHeight(120)
        # Live-update preview as the user types.
        self.system_prompt_edit.textChanged.connect(self._refresh_persona_preview)
        layout.addWidget(self.system_prompt_edit, 2)

        # Also update preview on metadata fields above.
        for w_edit in (self.name_input, self.user_address_input):
            w_edit.textChanged.connect(self._refresh_persona_preview)

        layout.addWidget(QLabel("发给 LLM 的完整 prompt（只读 · 自动拼接）："))
        self.persona_preview = QPlainTextEdit()
        self.persona_preview.setReadOnly(True)
        self.persona_preview.setMinimumHeight(100)
        self.persona_preview.setStyleSheet(
            "QPlainTextEdit { background-color: #1a1a24; color: #888; }"
        )
        layout.addWidget(self.persona_preview, 1)

        layout.addWidget(QLabel("示范对话（一行用户、一行助手，空行分隔）："))
        self.examples_edit = QPlainTextEdit()
        self.examples_edit.setMinimumHeight(100)
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
        self.user_address_input.setText(p.user_address)
        self.system_prompt_edit.setPlainText(p.system_prompt)
        self.examples_edit.setPlainText(_format_examples(p.examples))
        self._refresh_persona_preview()

    def _refresh_persona_preview(self) -> None:
        """Recompose the full system prompt from the current UI state and
        show it in the read-only preview. Cheap enough to re-run on every
        keystroke."""
        if not hasattr(self, "persona_preview"):
            return
        try:
            p = self._persona_from_ui()
            self.persona_preview.setPlainText(p.composed_system_prompt())
        except Exception:
            self.persona_preview.setPlainText("(无法预览)")

    def _persona_from_ui(self) -> Persona:
        return Persona(
            name=self.name_input.text().strip() or "小妹",
            display_prefix=self.prefix_input.text().strip() or "妹",
            system_prompt=self.system_prompt_edit.toPlainText().strip(),
            user_address=self.user_address_input.text().strip(),
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
            user_address=p.user_address,
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

        # Two stacked sections: extracted facts on top, recent episodes below.
        # Facts answer "what does she remember about me", episodes answer
        # "what did we just say"; users want both.
        layout.addWidget(QLabel("提炼事实（按重要度）："))
        self.facts_list = QListWidget()
        self.facts_list.setMinimumHeight(120)
        layout.addWidget(self.facts_list, 1)

        layout.addWidget(QLabel("最近对话片段（按时间倒序）："))
        self.episodes_list = QListWidget()
        self.episodes_list.setMinimumHeight(160)
        layout.addWidget(self.episodes_list, 2)

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
            self.episodes_list.clear()
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

        # Recent episodes (latest first). Show speaker prefix + truncated
        # text + relative timestamp so users can quickly scan.
        self.episodes_list.clear()
        recent = self.session.memory.episodic.recent(limit=50)
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        for ep in recent:
            try:
                ts = datetime.fromisoformat(ep.ts)
                ago_s = int((now - ts).total_seconds())
                if ago_s < 60:
                    when = f"{ago_s}s 前"
                elif ago_s < 3600:
                    when = f"{ago_s // 60}m 前"
                elif ago_s < 86400:
                    when = f"{ago_s // 3600}h 前"
                else:
                    when = f"{ago_s // 86400}d 前"
            except Exception:
                when = "?"
            text = ep.text.replace("\n", " ")
            if len(text) > 120:
                text = text[:120] + "…"
            self.episodes_list.addItem(f"[{when}] {ep.speaker}: {text}")

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

        # === TTS backend selection + per-backend params ===
        layout.addWidget(QLabel("<b>TTS 后端</b>"))
        voice_cfg = (self.cfg.get("voice") or {})
        overrides = preferences.get_voice_overrides()
        self._voice_overrides = dict(overrides)  # working copy

        cur_backend = (
            overrides.get("backend")
            or voice_cfg.get("backend")
            or "edge-tts"
        )

        self.tts_backend_combo = QComboBox()
        self.tts_backend_combo.addItem(
            "edge-tts（微软 Azure 免费 TTS，联网即可、零本地依赖）", "edge-tts"
        )
        self.tts_backend_combo.addItem(
            "gpt-sovits（本地克隆声音，需先跑 api_v2 server）", "gpt-sovits"
        )
        for i in range(self.tts_backend_combo.count()):
            if self.tts_backend_combo.itemData(i) == cur_backend:
                self.tts_backend_combo.setCurrentIndex(i)
                break
        self.tts_backend_combo.currentIndexChanged.connect(self._tts_backend_changed)
        layout.addWidget(self.tts_backend_combo)

        # edge-tts params (voice / rate / pitch)
        self._edge_box = QWidget()
        edge_form = QFormLayout(self._edge_box)
        edge_cfg = dict(voice_cfg.get("edge_tts") or {})
        edge_cfg.update(overrides.get("edge_tts") or {})

        self.edge_voice_combo = QComboBox()
        # A curated subset; users can hand-edit config.yaml for the rest.
        for v in [
            "zh-CN-XiaoxiaoNeural",
            "zh-CN-XiaoyiNeural",
            "zh-CN-YunjianNeural",
            "zh-CN-YunxiNeural",
            "zh-CN-YunxiaNeural",
            "zh-CN-YunyangNeural",
            "zh-CN-liaoning-XiaobeiNeural",
            "zh-CN-shaanxi-XiaoniNeural",
        ]:
            self.edge_voice_combo.addItem(v)
        cur_voice = edge_cfg.get("voice", "zh-CN-XiaoxiaoNeural")
        idx = self.edge_voice_combo.findText(cur_voice)
        if idx >= 0:
            self.edge_voice_combo.setCurrentIndex(idx)
        else:
            self.edge_voice_combo.addItem(cur_voice)
            self.edge_voice_combo.setCurrentText(cur_voice)
        edge_form.addRow("声音：", self.edge_voice_combo)

        self.edge_rate_edit = QLineEdit(edge_cfg.get("rate", "+0%"))
        self.edge_rate_edit.setPlaceholderText("如 +0% / +20% / -10%")
        edge_form.addRow("语速 rate：", self.edge_rate_edit)

        self.edge_pitch_edit = QLineEdit(edge_cfg.get("pitch", "+0Hz"))
        self.edge_pitch_edit.setPlaceholderText("如 +0Hz / +50Hz / -20Hz")
        edge_form.addRow("音调 pitch：", self.edge_pitch_edit)

        self.edge_volume_edit = QLineEdit(edge_cfg.get("volume", "+0%"))
        edge_form.addRow("音量 volume：", self.edge_volume_edit)
        layout.addWidget(self._edge_box)

        # gpt-sovits params
        self._sovits_box = QWidget()
        sovits_form = QFormLayout(self._sovits_box)
        sovits_cfg = dict(voice_cfg.get("sovits") or {})
        sovits_cfg.update(overrides.get("sovits") or {})

        self.sovits_url_edit = QLineEdit(
            sovits_cfg.get("base_url", "http://127.0.0.1:9880")
        )
        sovits_form.addRow("base_url：", self.sovits_url_edit)
        self.sovits_ref_audio_edit = QLineEdit(sovits_cfg.get("ref_audio", ""))
        self.sovits_ref_audio_edit.setPlaceholderText("3-10s 干净参考音频的绝对路径")
        sovits_form.addRow("ref_audio：", self.sovits_ref_audio_edit)
        self.sovits_ref_text_edit = QLineEdit(sovits_cfg.get("ref_text", ""))
        self.sovits_ref_text_edit.setPlaceholderText("ref_audio 的逐字转录")
        sovits_form.addRow("ref_text：", self.sovits_ref_text_edit)
        layout.addWidget(self._sovits_box)

        # Save row for backend params
        save_voice_row = QHBoxLayout()
        save_voice_row.addStretch(1)
        save_voice_btn = QPushButton("保存语音设置")
        save_voice_btn.clicked.connect(self._save_voice_overrides)
        save_voice_row.addWidget(save_voice_btn)
        layout.addLayout(save_voice_row)

        self._tts_backend_changed()  # toggle visibility based on initial pick

        # === Audio output device (existing) ===
        layout.addSpacing(12)
        layout.addWidget(QLabel("<b>音频输出设备</b>"))
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

    def _tts_backend_changed(self) -> None:
        """Show only the params box matching the selected backend."""
        backend = self.tts_backend_combo.currentData()
        self._edge_box.setVisible(backend == "edge-tts")
        self._sovits_box.setVisible(backend == "gpt-sovits")

    def _save_voice_overrides(self) -> None:
        """Persist the TTS backend choice + per-backend params to
        preferences.yaml. Takes effect on next restart (the Speaker is
        constructed once at startup; can't hot-swap the underlying backend
        without rebuilding the whole pipeline)."""
        from core import preferences

        backend = self.tts_backend_combo.currentData()
        overrides: dict = {"backend": backend}
        if backend == "edge-tts":
            overrides["edge_tts"] = {
                "voice": self.edge_voice_combo.currentText().strip(),
                "rate": self.edge_rate_edit.text().strip() or "+0%",
                "pitch": self.edge_pitch_edit.text().strip() or "+0Hz",
                "volume": self.edge_volume_edit.text().strip() or "+0%",
            }
        else:  # gpt-sovits
            overrides["sovits"] = {
                "base_url": self.sovits_url_edit.text().strip(),
                "ref_audio": self.sovits_ref_audio_edit.text().strip(),
                "ref_text": self.sovits_ref_text_edit.text().strip(),
            }
        preferences.set_voice_overrides(overrides)
        self._voice_overrides = overrides

        # Live-apply: merge overrides into the running cfg and hand the
        # parent window a freshly-constructed backend. No restart needed --
        # the currently-playing sentence finishes on the old backend, the
        # next one picks up the new settings.
        parent = self.parent()
        if parent is not None and hasattr(parent, "reload_voice"):
            voice_cfg = parent.cfg.setdefault("voice", {})
            for k, v in overrides.items():
                if isinstance(v, dict) and isinstance(voice_cfg.get(k), dict):
                    voice_cfg[k] = {**voice_cfg[k], **v}
                else:
                    voice_cfg[k] = v
            parent.reload_voice()

        QMessageBox.information(
            self,
            "已保存",
            f"语音设置已应用（{backend}）。下条消息生效。",
        )

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

    # ---------------------------------------------------------------- form

    def _build_form_tab(self) -> QWidget:
        """Bind each standard emotion to one of the model's actual
        expressions or motions. Replaces the heuristic guess from
        import_live2d with explicit user choice, saved back to imouto.yaml."""
        from typing import Any

        from core.live2d_binding import (
            STANDARD_EMOTIONS,
            ModelBindings,
            load_bindings,
        )

        w = QWidget()
        layout = QVBoxLayout(w)

        parent = self.parent()
        model_dir = None
        if parent is not None and hasattr(parent, "live2d_cfg"):
            model_dir = parent.live2d_cfg.model_dir

        # When no model is installed, this tab doubles as the install wizard
        # so users don't have to restart the app just to redo a first-run
        # action that's lived only on launch until now.
        model_file = model_dir / parent.live2d_cfg.model_file if (
            model_dir is not None and parent is not None
        ) else None
        has_model = model_file is not None and model_file.is_file()
        if not has_model:
            layout.addWidget(QLabel("还没有安装 Live2D 模型。"))
            layout.addWidget(QLabel(
                "去 Live2D 官方下载一个 sample（推荐带表情的 Mark / Haru），"
                "然后选择那个 zip 文件就能装上。"
            ))
            btn_row = QHBoxLayout()
            open_site_btn = QPushButton("打开 Live2D 下载页")
            open_site_btn.clicked.connect(
                lambda: self._open_url("https://www.live2d.com/en/learn/sample/")
            )
            pick_zip_btn = QPushButton("选择已下载的 zip")
            pick_zip_btn.clicked.connect(self._form_install_zip)
            btn_row.addWidget(open_site_btn)
            btn_row.addWidget(pick_zip_btn)
            btn_row.addStretch(1)
            layout.addLayout(btn_row)
            layout.addStretch(1)
            return w

        bindings: ModelBindings = load_bindings(model_dir)
        self._form_bindings = bindings

        # Two-row header: status on top, controls below. A single row
        # couldn't fit all widgets at 640px dialog width -- the switch
        # combobox got clipped off-screen and users couldn't find it.

        # Row 1: current model name + counts
        layout.addWidget(QLabel(
            f"当前模型：<b>{model_dir.name}</b>  ·  "
            f"{len(bindings.expressions)} 个表情 · "
            f"{len(bindings.motions)} 个动作"
        ))

        # Row 2: switch dropdown + install / download buttons
        controls = QHBoxLayout()
        installed = self._list_installed_models()
        if len(installed) > 1:
            controls.addWidget(QLabel("切换已装："))
            switch_combo = QComboBox()
            for name in installed:
                switch_combo.addItem(name)
            switch_combo.setCurrentText(model_dir.name)
            switch_combo.currentTextChanged.connect(self._form_switch_to)
            controls.addWidget(switch_combo, 1)

        switch_btn = QPushButton("装新模型 zip")
        switch_btn.clicked.connect(self._form_install_zip)
        controls.addWidget(switch_btn)

        site_btn = QPushButton("下载页")
        site_btn.clicked.connect(
            lambda: self._open_url("https://www.live2d.com/en/learn/sample/")
        )
        controls.addWidget(site_btn)
        controls_w = QWidget()
        controls_w.setLayout(controls)
        layout.addWidget(controls_w)

        # Option list shared by every dropdown. Each entry's userData is
        # either:
        #   None                — unbound
        #   ("expr", name: str) — bind to expression
        #   ("motion", group: str, index: int) — bind to motion
        options: list[tuple[str, Any]] = [("（无）", None)]
        for expr in bindings.expressions:
            options.append((f"[表情] {expr}", ("expr", expr)))
        for m in bindings.motions:
            options.append((m.label(), ("motion", m.group, m.index)))

        form = QFormLayout()
        self._form_combos: dict[str, QComboBox] = {}
        for emo in STANDARD_EMOTIONS:
            row = QHBoxLayout()
            combo = QComboBox()
            for label, data in options:
                combo.addItem(label, data)
            # Preselect the current binding (expression wins over motion).
            cur_expr = bindings.emotion_to_expression.get(emo)
            cur_motion = bindings.emotion_to_motion.get(emo)
            preselect: Any = None
            if cur_expr is not None:
                preselect = ("expr", cur_expr)
            elif cur_motion is not None:
                preselect = ("motion", cur_motion.group, cur_motion.index)
            if preselect is not None:
                for i in range(combo.count()):
                    if combo.itemData(i) == preselect:
                        combo.setCurrentIndex(i)
                        break
            self._form_combos[emo] = combo
            row.addWidget(combo, 1)

            preview_btn = QPushButton("试")
            preview_btn.setFixedWidth(40)
            preview_btn.clicked.connect(
                lambda _=False, e=emo: self._form_preview(e)
            )
            row.addWidget(preview_btn)

            wrap = QWidget()
            wrap.setLayout(row)
            form.addRow(emo + "：", wrap)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._form_save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        self._form_status = QLabel("")
        self._form_status.setStyleSheet("color: #aaa;")
        layout.addWidget(self._form_status)

        layout.addStretch(1)
        return w

    def _form_preview(self, emotion: str) -> None:
        """Fire the currently-selected expression/motion live in the WebView
        so the user can confirm the binding before saving."""
        import json

        combo = self._form_combos.get(emotion)
        if combo is None:
            return
        data = combo.currentData()
        parent = self.parent()
        if parent is None or not hasattr(parent, "view"):
            return
        if data is None:
            js = "if(window.imouto) window.imouto.clearExpression();"
        elif data[0] == "expr":
            js = (
                "if(window.imouto) window.imouto.setExpression("
                + json.dumps(data[1], ensure_ascii=False)
                + ");"
            )
        elif data[0] == "motion":
            grp = json.dumps(data[1], ensure_ascii=False)
            js = f"if(window.imouto) window.imouto.playMotion({grp}, {int(data[2])});"
        else:
            return
        parent.view.page().runJavaScript(js)
        self._form_status.setText(f"试播：{emotion} → {combo.currentText()}")

    def _form_save(self) -> None:
        from core.live2d_binding import MotionRef, save_bindings

        b = self._form_bindings
        b.emotion_to_expression = {}
        b.emotion_to_motion = {}
        for emo, combo in self._form_combos.items():
            data = combo.currentData()
            if data is None:
                continue
            if data[0] == "expr":
                b.emotion_to_expression[emo] = data[1]
            elif data[0] == "motion":
                b.emotion_to_motion[emo] = MotionRef(group=data[1], index=int(data[2]))
        try:
            save_bindings(b)
        except Exception as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return

        # Live-update the running Live2DConfig so the next emotion tag uses
        # the new binding without requiring a restart.
        parent = self.parent()
        if parent is not None and hasattr(parent, "live2d_cfg"):
            parent.live2d_cfg.emotion_mapping = dict(b.emotion_to_expression)
            parent.live2d_cfg.motion_mapping = {
                emo: m.as_dict() for emo, m in b.emotion_to_motion.items()
            }
        self._form_status.setText("已保存（下条消息生效）")

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

            # "获取" button opens the provider's API-key console in the
            # default browser. Only added when we know where to send them.
            url_info = env_file.KEY_SOURCES.get(env_name)
            if url_info:
                get_btn = QPushButton("获取")
                get_btn.setFixedWidth(56)
                get_btn.setToolTip(url_info[1])
                get_btn.clicked.connect(
                    lambda _=False, u=url_info[0]: self._open_url(u)
                )
                row.addWidget(get_btn)

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

        # --- local backend (LM Studio / Ollama / llama.cpp / vLLM) ---
        layout.addSpacing(12)
        layout.addWidget(QLabel("<b>本地后端</b>（LM Studio / Ollama / llama.cpp 等）"))

        local_cur = preferences.get_local_backend()
        local_default = (
            ((self.cfg.get("brain") or {}).get("backends") or {}).get("local-qwen")
            or {}
        )
        local_form = QFormLayout()

        self.local_url_input = QLineEdit(
            local_cur.get("base_url") or local_default.get("base_url") or ""
        )
        self.local_url_input.setPlaceholderText(
            "LM Studio: http://127.0.0.1:1234/v1   "
            "Ollama: http://127.0.0.1:11434/v1"
        )
        local_form.addRow("base_url：", self.local_url_input)

        self.local_model_input = QLineEdit(
            local_cur.get("model") or local_default.get("model") or ""
        )
        self.local_model_input.setPlaceholderText(
            "服务端列出的 model id，如 qwen/qwen3-vl-30b"
        )
        local_form.addRow("model：", self.local_model_input)

        layout.addLayout(local_form)

        local_btn_row = QHBoxLayout()
        save_local_btn = QPushButton("保存本地后端")
        save_local_btn.clicked.connect(self._save_local_backend)
        local_btn_row.addWidget(save_local_btn)
        local_btn_row.addStretch(1)
        layout.addLayout(local_btn_row)

        hint2 = QLabel(
            "保存后选「local-qwen」作为默认聊天后端，"
            "或在路由里指定具体任务用它。重启或测试连通时生效。"
        )
        hint2.setStyleSheet("color: #aaa;")
        hint2.setWordWrap(True)
        layout.addWidget(hint2)

        layout.addStretch(1)
        return w

    def _save_local_backend(self) -> None:
        """Persist user's LM Studio / Ollama endpoint to preferences and
        live-update the existing local-qwen backend so the next chat (or
        test-connectivity click) hits the new endpoint without restart."""
        from core import preferences

        url = self.local_url_input.text().strip()
        model = self.local_model_input.text().strip()
        if not url or not model:
            QMessageBox.warning(
                self, "缺字段", "base_url 和 model 都要填。"
            )
            return
        preferences.set_local_backend(base_url=url, model=model)
        # Live update: rebuild the local-qwen backend on the running
        # router so /test connectivity picks up the new URL immediately.
        if self.session is not None and self.session.router is not None:
            backend = self.session.router.backends.get("local-qwen")
            if backend is not None:
                backend.base_url = url.rstrip("/")
                backend.model = model
        QMessageBox.information(
            self,
            "已保存",
            f"本地后端已指向：\n{url}\n模型：{model}\n\n"
            "选「local-qwen」作为默认聊天后端来用它。",
        )

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

    def _open_url(self, url: str) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl(url))

    def _form_install_zip(self) -> None:
        """File-picker → installer, same as the first-run wizard but
        triggered from the form tab so users can install a model any time."""
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        zip_str, _ = QFileDialog.getOpenFileName(
            self, "选择 Live2D 模型 zip", "", "Zip 文件 (*.zip)"
        )
        if not zip_str:
            return
        parent = self.parent()
        if parent is not None and hasattr(parent, "_install_live2d_zip"):
            parent._install_live2d_zip(Path(zip_str))

    def _list_installed_models(self) -> list[str]:
        """Return folder names under live2d/models/ that look like installed
        models (have a model3.json)."""
        from pathlib import Path

        models_root = Path("live2d/models")
        if not models_root.is_dir():
            return []
        out = []
        for d in sorted(models_root.iterdir()):
            if d.is_dir() and any(d.glob("*.model3.json")):
                out.append(d.name)
        return out

    def _form_switch_to(self, name: str) -> None:
        """Switch active model to an already-installed one. Writes the choice
        to preferences and tells the parent window to reload the Live2D view
        in place -- no restart needed."""
        from core import preferences

        cur = preferences.get_live2d_active_model()
        if cur == name:
            return
        preferences.set_live2d_active_model(name)
        parent = self.parent()
        if parent is not None and hasattr(parent, "reload_live2d_model"):
            parent.reload_live2d_model()

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

        # If the user just unlocked a backend (saved a key for an env var)
        # while the current default chat backend has no key, auto-switch the
        # default to the first backend that now has a valid key. Saves the
        # "save key → go change default → save again" two-step.
        auto_switched = self._maybe_auto_switch_backend(env_name)

        msg = f"{env_name} 已写入 .env。"
        if auto_switched:
            msg += f"\n\n已自动切换默认后端为：<b>{auto_switched}</b>"
        else:
            msg += "\n\n切换后端或重启 app 让所有路径生效。"
        QMessageBox.information(self, "已保存", msg)

    def _maybe_auto_switch_backend(self, just_saved_env: str) -> str | None:
        """If the running default backend has no api_key, look for a backend
        whose api_key_env was just satisfied (or any other backend with a
        valid key) and switch to it. Returns the new backend's name on
        success, or None if no switch was needed/possible."""
        from core import preferences

        router = self.session.router if self.session is not None else None
        if router is None:
            return None
        cur_backend = router.backends.get(router.default)
        if cur_backend is not None and getattr(cur_backend, "api_key", ""):
            # Default already has a key. Nothing to do.
            return None

        # Prefer a backend that uses the env var we just saved.
        def has_live_key(b) -> bool:
            return bool(getattr(b, "api_key", "") or "")

        candidates_pref = [
            (name, b) for name, b in router.backends.items()
            if getattr(b, "api_key_env", None) == just_saved_env and has_live_key(b)
        ]
        candidates_any = [
            (name, b) for name, b in router.backends.items()
            if has_live_key(b)
        ]
        target = (candidates_pref or candidates_any)
        if not target:
            return None
        new_name, _ = target[0]
        router.default = new_name
        preferences.set_chat_backend(new_name)
        # Reflect in the combobox so the UI stays in sync.
        if hasattr(self, "backend_combo"):
            for i in range(self.backend_combo.count()):
                if self.backend_combo.itemData(i) == new_name:
                    was_blocked = self.backend_combo.blockSignals(True)
                    self.backend_combo.setCurrentIndex(i)
                    self.backend_combo.blockSignals(was_blocked)
                    break
        return new_name

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
            # Reasoning models (gpt-5.x, gemini-3.1-pro) eat their first
            # tokens on hidden reasoning, so a tight budget like 8 leaves
            # no room for visible content. 256 is enough for "hi"-class
            # replies on any model.
            req = ChatRequest(
                messages=[Message(role="user", content=[ContentPart(type="text", text="hi")])],
                stream=False,
                max_tokens=256,
            )
            reply = ""
            async for chunk in backend.chat(req):
                reply += chunk.delta
            return reply

        self.model_status.setText(f"测试 {name} ...")
        task = asyncio.ensure_future(run())

        def done(t: asyncio.Task) -> None:
            try:
                t.result()
                # Don't surface the actual reply text -- whether the model
                # said "hi" or stayed silent isn't useful here; the user
                # just wants to know auth + request format are working.
                self.model_status.setText(f"{name}: ✓ 连通正常")
            except Exception as e:
                self.model_status.setText(f"{name}: ✗ {type(e).__name__}: {e}")

        task.add_done_callback(done)
