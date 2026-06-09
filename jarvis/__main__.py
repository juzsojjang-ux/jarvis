from __future__ import annotations

import asyncio
import contextlib
import os

from anthropic import AsyncAnthropic

from .activation.ptt import PushToTalk
from .audio.capture import MicCapture
from .audio.playback import Playback
from .brain.claude import Brain
from .brain.memory import MemoryStore
from .brain.persona import load_persona
from .brain.sentence import SentenceChunker
from .core.config import Settings
from .core.orchestrator import Orchestrator
from .stt.mlx_whisper import MLXWhisperSTT
from .tools.builtin.local_tools import calc, make_remember_tool
from .tools.builtin.time_weather import get_time, get_weather
from .tools.builtin.web_search import WEB_SEARCH_TOOL
from .tools.confirm import VoiceConfirm
from .tools.mcp_client import DEFAULT_MCP_SERVERS, load_mcp_tools
from .tools.registry import ToolRegistry
from .tts.factory import make_tts
from .vc.factory import make_vc


async def build_orchestrator(
    *,
    client: AsyncAnthropic | None = None,
    exit_stack: contextlib.AsyncExitStack | None = None,
) -> Orchestrator:
    """Construct the full assistant. ALL backend/tool/Brain construction lives
    HERE — never in Orchestrator.__init__. When ``exit_stack`` is supplied (by
    _amain, held open for the process lifetime) any enabled MCP servers are
    loaded into the registry through it.
    """
    settings = Settings()
    memory = MemoryStore(settings.memory_path)
    memory.load()
    persona = load_persona(settings.persona_path)  # real >=4096-token persona; no fallback

    # Shared backends (constructed here, then dependency-injected).
    activator = PushToTalk(settings.ptt_key)
    capture = MicCapture(sample_rate=16000)
    stt = MLXWhisperSTT(settings.stt_repo, language=settings.language)
    tts = make_tts(settings)
    vc = make_vc(settings)
    playback = Playback(sample_rate=settings.playback_rate)
    chunker = SentenceChunker()

    # Real voice confirmation for gated (irreversible) tools.
    confirmer = VoiceConfirm(
        tts=tts, vc=vc, playback=playback, capture=capture, stt=stt, settings=settings
    )

    # Tool catalog: local builtins + server web_search + remember + calc.
    registry = ToolRegistry()
    registry.register(get_time)
    registry.register(get_weather)
    registry.register(WEB_SEARCH_TOOL)
    registry.register(make_remember_tool(memory))
    registry.register(calc)

    # MCP tools via the caller-owned AsyncExitStack (held open for process life).
    if exit_stack is not None:
        mcp_tools, _search = await load_mcp_tools(DEFAULT_MCP_SERVERS, exit_stack)
        for tool in mcp_tools:
            registry.register(tool, gated=True)  # MCP actions are irreversible

    brain = Brain(
        settings,
        memory,
        persona,
        client=client,
        registry=registry,
        confirm=confirmer.confirm,
    )

    return Orchestrator(
        settings=settings,
        activator=activator,
        capture=capture,
        stt=stt,
        brain=brain,
        chunker=chunker,
        tts=tts,
        vc=vc,
        playback=playback,
    )


async def _amain() -> None:
    # AsyncExitStack stays open for the whole process lifetime (MCP sessions live).
    async with contextlib.AsyncExitStack() as stack:
        orch = await build_orchestrator(exit_stack=stack)
        # Warm models + persona cache before listening.
        orch.stt.warm()
        orch.tts.warm()
        orch.vc.warm()
        await orch.brain.warm()
        print("자비스 준비 완료. 오른쪽 옵션 키를 누른 채 말씀하세요. (Ctrl+C로 종료)")
        await orch.run()


def main() -> None:
    # After the first model download, run with HF_HUB_OFFLINE=1 for fully local STT.
    os.environ.setdefault("HF_HUB_OFFLINE", os.environ.get("HF_HUB_OFFLINE", "0"))
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        print("\n종료합니다.")


if __name__ == "__main__":
    main()
