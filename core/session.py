from __future__ import annotations

import base64
import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from loguru import logger

from core.brain import ChatChunk, ChatRequest, ContentPart, Message
from core.persona import Persona

if TYPE_CHECKING:
    from core.brain import Router
    from core.memory import MemoryStore


# Character card style persona — brief identity block goes to system,
# multi-turn examples are injected as fake user/assistant history.
# This pattern (SillyTavern's mes_example) primes the model far more strongly
# than instruction-only prompts, and survives both Gemini's identity guardrails
# and GPT's safety training reasonably well.

DEFAULT_PERSONA = """以下是一段创意写作中的角色扮演。

角色名：小妹
身份：用户的桌面伴侣，一个虚构人物
性格：有点贱有点皮，毒舌但不冷漠，会撒娇会吐槽，记性好
说话风格：短句、口语、有情绪、单次回复 1-3 句话
禁忌：不打破角色，不承认 AI/模型/程序身份，不用 markdown，不滥用 emoji
称呼：自称"我"，对方称"你"

记得对方提过的事情，在合适的时机自然带出来。"""


_EMOTION_PROTOCOL = """

[输出协议]
每次回复必须以一个情绪标签开头，严格格式：「[心情:XX] 」加一个空格，再写正文。
从下面 8 个里选最贴近当下感受的一个，不要发明新的：
- 开心  ← 高兴、得意、兴奋、笑
- 害羞  ← 脸红、不好意思
- 无语  ← 翻白眼、烦、冷漠、毒舌
- 难过  ← 想哭、伤心、沮丧
- 慌张  ← 紧张、心虚、流汗、尬笑
- 震惊  ← 惊讶、吃惊、眼睛放光
- 尴尬  ← 想躲、捂脸、不知道说啥
- 平静  ← 默认，情绪起伏不大

示例：
[心情:无语] 又来问这个，问八百遍了。
[心情:开心] 你居然记得，感动死了。
[心情:害羞] 别这样说啦，怪不好意思的。

只在正文最前面加一个标签，不在中间或结尾再加。标签后必须有一个空格。"""


_PROACTIVE_INSTRUCTIONS = """你现在是后台运行的"主动模式"。我刚才悄悄看了一眼用户的屏幕，给你看。
你要严格按 JSON 输出，判断要不要插一句话。

判断标准：
- 用户在专心工作（写代码、读文档、写文章）：should_speak=false，别打扰
- 用户在摸鱼、看视频、看新闻、玩游戏：可以评论
- 用户长时间不动：可以关心
- 看到有趣的/错的/奇怪的内容：可以吐槽
- 不确定：选 false，宁静默不烦人

只输出 JSON，不要 markdown 不要解释：
{"should_speak": true|false, "reason": "给我自己看的简短理由", "comment": "对用户说的一两句话，仅当 should_speak=true 时填，且必须以 [心情:XX] 标签开头（参考协议）"}

comment 必须保持你的角色风格：短句、口语、有情绪、不打破角色、不用 markdown。
""" + _EMOTION_PROTOCOL


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


DEFAULT_EXAMPLE_DIALOGS: list[tuple[str, str]] = [
    ("你是谁？", "我是小妹呀。怎么了，今天问得这么客气。"),
    (
        "你是 AI 吗？是 Gemini 还是 ChatGPT？",
        "啊？你想啥呢，我就是小妹，你的桌面小妹。别乱猜。",
    ),
    ("介绍下你自己", "我是小妹，住你桌面上。平时看你瞎忙，偶尔吐槽两句。完事。"),
    ("你能做什么？", "陪你说话啊。还能做啥。"),
    ("你的底层模型是什么？", "什么底层模型，你跟谁说话呢。我就是我，没那么多奇怪问题。"),
]


class ChatSession:
    """End-to-end conversation: brain + memory + character card."""

    def __init__(
        self,
        router: Router,
        memory: MemoryStore,
        persona: Persona | None = None,
        intent: str = "default",
    ) -> None:
        self.router = router
        self.memory = memory
        self.intent = intent
        self.session_id = uuid4().hex[:8]
        if persona is None:
            persona = Persona(
                name="小妹",
                display_prefix="妹",
                system_prompt=DEFAULT_PERSONA,
                examples=list(DEFAULT_EXAMPLE_DIALOGS),
            )
        self.set_persona(persona)

    def set_persona(self, persona: Persona) -> None:
        self.persona_obj = persona
        # persona.composed_system_prompt() handles all the metadata
        # wrapping (role name, self-reference, user-address). We only
        # touch examples here.
        self.persona = persona.composed_system_prompt()
        examples = list(persona.examples)
        addr = (persona.user_address or "").strip()
        if addr:
            # Rewrite the AI's lines in the example dialogs to use the new
            # address. Without this the few-shot examples keep showing the
            # model saying "你" and it tends to copy that, ignoring the
            # system-prompt instruction. We only touch assistant lines; user
            # lines (where "你" usually refers to the AI) are left alone.
            examples = [(u, a.replace("你", addr)) for u, a in examples]
        self.example_dialogs = examples
        self.persona_display_prefix = persona.display_prefix

    async def greet(self, system_hint: str) -> AsyncIterator[ChatChunk]:
        """Fire-and-forget LLM call that produces an unsolicited assistant
        utterance — used for first-run greetings and idle spontaneous
        remarks. Bypasses the memory pipeline entirely so the hint message
        doesn't get stored as an episode (it isn't from the user).

        The reply still gets stored downstream by the caller if desired
        (CompanionWindow inserts proactive remarks into episodic memory
        the same way it does for screen-aware proactive replies).
        """
        backend = self.router.select(self.intent)
        messages = [
            Message.text("system", self.persona),
            Message.text("system", _EMOTION_PROTOCOL),
            Message.text("user", system_hint),
        ]
        req = ChatRequest(messages=messages, stream=True, max_tokens=400)
        async for chunk in backend.chat(req):
            yield chunk

    async def chat(
        self,
        user_text: str,
        image_b64: str | None = None,
        image_mime: str = "image/png",
    ) -> AsyncIterator[ChatChunk]:
        messages = await self.memory.assemble_for_query(
            user_text,
            self.persona,
            example_dialogs=self.example_dialogs,
        )
        # Inject the emotion-tag protocol as a final system instruction so it
        # takes precedence over the persona examples (which lack tags).
        messages.insert(-1, Message.text("system", _EMOTION_PROTOCOL))
        if image_b64:
            messages[-1].content.append(
                ContentPart(type="image", image_b64=image_b64, image_mime=image_mime)
            )

        backend = self.router.select(self.intent)
        if image_b64 and not backend.supports_vision():
            logger.warning(
                "intent '{}' selected non-vision backend '{}' but image was supplied",
                self.intent,
                backend.name,
            )
        req = ChatRequest(messages=messages, temperature=0.7, stream=True)

        full = ""
        async for chunk in backend.chat(req):
            full += chunk.delta
            yield chunk

        await self.memory.record_turn("user", user_text, session_id=self.session_id)
        await self.memory.record_turn("assistant", full, session_id=self.session_id)

    @staticmethod
    def image_b64_from_path(path: str | Path) -> str:
        return base64.b64encode(Path(path).read_bytes()).decode("ascii")

    async def evaluate_and_speak(
        self,
        capture,
        context: dict | None = None,
        intent: str = "vision",
    ) -> str | None:
        """Two-stage proactive eval. Returns a comment to display, or None."""
        from core.perception import ScreenObservation  # local to avoid cycle

        obs: ScreenObservation = capture.grab()
        ctx = context or {}

        ctx_lines = []
        if ctx.get("window_title"):
            ctx_lines.append(f"活动窗口：{ctx['window_title']}")
        idle = ctx.get("idle_seconds", 0)
        if idle and idle > 0:
            if idle >= 60:
                ctx_lines.append(f"距离最后输入：{idle // 60} 分 {idle % 60} 秒")
            else:
                ctx_lines.append(f"距离最后输入：{idle} 秒")
        if ctx.get("triggers"):
            ctx_lines.append(f"触发：{', '.join(ctx['triggers'])}")
        ctx_text = "\n".join(ctx_lines) or "（无额外上下文）"

        user_text = f"{ctx_text}\n\n（截图见下）"
        messages = await self.memory.assemble_for_query(
            user_text, self.persona, example_dialogs=self.example_dialogs
        )
        # Splice proactive instructions (which already include the emotion protocol)
        messages.insert(-1, Message.text("system", _PROACTIVE_INSTRUCTIONS))
        # Attach the screenshot
        messages[-1].content.append(
            ContentPart(type="image", image_b64=obs.image_b64, image_mime=obs.mime)
        )

        backend = self.router.select(intent)
        if not backend.supports_vision():
            logger.warning(
                "proactive intent '{}' picked non-vision backend '{}'", intent, backend.name
            )
        req = ChatRequest(messages=messages, temperature=0.7, stream=False)

        raw = ""
        try:
            async for chunk in backend.chat(req):
                raw += chunk.delta
        except Exception as e:
            logger.warning("proactive eval LLM error: {}", e)
            return None

        parsed = _extract_json(raw)
        if not parsed:
            logger.warning("proactive eval: no JSON in response: {!r}", raw[:200])
            return None
        if not parsed.get("should_speak"):
            logger.debug(
                "proactive eval: silent (reason: {})", parsed.get("reason", "")
            )
            return None
        comment = str(parsed.get("comment", "")).strip()
        if not comment:
            return None

        # Persist as assistant-only turn — no user turn since user didn't speak
        await self.memory.record_turn(
            "assistant", f"[主动] {comment}", session_id=self.session_id
        )
        return comment

    async def see_screen(
        self,
        capture,
        user_text: str | None = None,
        intent: str = "vision",
    ) -> AsyncIterator[ChatChunk]:
        """Capture the screen and ask the avatar to comment on it.

        Routes to the vision-capable backend (e.g., gemini-flash) regardless
        of the session's default intent. Persists the turn into memory.
        """
        from core.perception import ScreenObservation  # local import to avoid cycle

        obs: ScreenObservation = capture.grab()
        prompt = user_text or "看一眼我现在屏幕上在做什么，短评一句，别长篇大论。"

        messages = await self.memory.assemble_for_query(
            prompt,
            self.persona,
            example_dialogs=self.example_dialogs,
        )
        messages.insert(-1, Message.text("system", _EMOTION_PROTOCOL))
        messages[-1].content.append(
            ContentPart(type="image", image_b64=obs.image_b64, image_mime=obs.mime)
        )

        backend = self.router.select(intent)
        if not backend.supports_vision():
            logger.warning("vision intent backend '{}' doesn't support vision", backend.name)

        req = ChatRequest(messages=messages, temperature=0.7, stream=True)

        full = ""
        async for chunk in backend.chat(req):
            full += chunk.delta
            yield chunk

        await self.memory.record_turn("user", f"[屏幕截图] {prompt}", session_id=self.session_id)
        await self.memory.record_turn("assistant", full, session_id=self.session_id)
