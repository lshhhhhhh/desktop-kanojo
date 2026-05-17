from __future__ import annotations

from typing import TYPE_CHECKING

from core.brain import Message

if TYPE_CHECKING:
    from .episodic import EpisodicStore
    from .facts import Fact, FactStore
    from .working import WorkingMemory


def render_facts_block(facts: list["Fact"]) -> str:
    if not facts:
        return ""
    lines = ["[关于用户的已知事实]"]
    for f in facts:
        lines.append(f"- {f.key}: {f.value}")
    return "\n".join(lines)


def render_episodes_block(episodes: list) -> str:
    if not episodes:
        return ""
    lines = ["[相关历史对话片段]"]
    for ep in episodes:
        date = ep.ts[:10] if ep.ts else ""
        lines.append(f"({date}) [{ep.speaker}] {ep.text}")
    return "\n".join(lines)


async def assemble_context(
    *,
    user_text: str,
    persona: str,
    working: "WorkingMemory",
    fact_store: "FactStore",
    episodic_store: "EpisodicStore",
    top_k_episodes: int = 5,
    example_dialogs: list[tuple[str, str]] | None = None,
) -> list[Message]:
    """Build the message list to send to the LLM.

    Order:
        1. system: persona + active facts (L3)
        2. example user/assistant pairs (character card mes_example, optional)
        3. system: retrieved relevant episodes (L2, optional)
        4. recent turns: working window (L1)
        5. user: the new query
    """
    facts = fact_store.all_active()
    facts_block = render_facts_block(facts)
    system_text = persona
    if facts_block:
        system_text = f"{persona}\n\n{facts_block}"
    messages: list[Message] = [Message.text("system", system_text)]

    if example_dialogs:
        for ex_user, ex_assistant in example_dialogs:
            messages.append(Message.text("user", ex_user))
            messages.append(Message.text("assistant", ex_assistant))

    retrieved = await episodic_store.search(user_text, top_k=top_k_episodes)
    if retrieved:
        eps = [ep for ep, _ in retrieved]
        messages.append(Message.text("system", render_episodes_block(eps)))

    for turn in working.turns():
        messages.append(Message.text(turn.speaker, turn.text))

    messages.append(Message.text("user", user_text))
    return messages
