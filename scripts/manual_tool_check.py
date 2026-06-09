"""Manual M3 live-API check (NOT a pytest — hits the real Claude API).

Two scenarios against the real claude-opus-4-8 TASK path:
  1) "지금 몇 시야?"            -> get_time dispatched, Korean time spoken (acceptance #1)
  2) "3 더하기 5 알려주고 메모해줘" -> calc(=8) + remember dispatched, spoken answer

Run:
    ~/jarvis/.venv/bin/python ~/jarvis/scripts/manual_tool_check.py
"""
import asyncio

import keyring
from anthropic import AsyncAnthropic

from jarvis.brain.claude import Brain
from jarvis.brain.persona import load_persona
from jarvis.core.config import Settings
from jarvis.tools.builtin.local_tools import calc, make_remember_tool
from jarvis.tools.builtin.time_weather import get_time, get_weather
from jarvis.tools.builtin.web_search import WEB_SEARCH_TOOL
from jarvis.tools.registry import ToolRegistry


class _Memory:
    def __init__(self) -> None:
        self.notes: list[str] = []

    def text(self) -> str:
        return "사용자 이름은 이성재. 한국어로 답한다."

    def remember(self, note: str) -> None:
        self.notes.append(note)
        print(f"[REMEMBER] {note!r}")


async def _confirm(prompt: str) -> bool:
    print(f"[VOICE-CONFIRM] {prompt} -> auto-YES")
    return True


async def _run(brain: Brain, registry: ToolRegistry, user_text: str) -> None:
    original = registry.dispatch

    async def traced(name, args):
        print(f"[DISPATCH] {name}({args})")
        return await original(name, args)

    registry.dispatch = traced  # type: ignore[assignment]
    print(f"\nUSER: {user_text}")
    print("JARVIS: ", end="", flush=True)
    async for delta in brain.respond(user_text):
        print(delta, end="", flush=True)
    print()
    registry.dispatch = original  # type: ignore[assignment]


async def main() -> None:
    settings = Settings()
    api_key = keyring.get_password("jarvis", "anthropic_api_key")
    client = AsyncAnthropic(api_key=api_key)
    persona = load_persona(settings.persona_path)
    memory = _Memory()

    registry = ToolRegistry()
    registry.register(get_time)
    registry.register(get_weather)
    registry.register(WEB_SEARCH_TOOL)
    registry.register(make_remember_tool(memory))
    registry.register(calc)

    brain = Brain(settings, memory, persona, client=client, registry=registry, confirm=_confirm)

    await _run(brain, registry, "지금 몇 시야?")
    await _run(brain, registry, "3 더하기 5 알려주고 메모해줘")


if __name__ == "__main__":
    asyncio.run(main())
