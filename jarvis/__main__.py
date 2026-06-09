from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
import webbrowser

from anthropic import AsyncAnthropic

from .activation.ptt import PushToTalk
from .audio.capture import MicCapture
from .audio.playback import Playback
from .brain.factory import make_brain
from .brain.memory import MemoryStore
from .brain.persona import load_persona
from .brain.sentence import SentenceChunker
from .core.config import Settings
from .core.orchestrator import Orchestrator
from .hud.orb_server import OrbServer
from .stt.mlx_whisper import MLXWhisperSTT
from .tools.builtin.local_tools import calc, make_remember_tool
from .tools.builtin.time_weather import get_time, get_weather
from .tools.builtin.voice_status import make_voice_status_tool
from .tools.builtin.web_search import WEB_SEARCH_TOOL
from .tools.confirm import VoiceConfirm
from .tools.mcp_client import DEFAULT_MCP_SERVERS, load_mcp_tools
from .tools.registry import ToolRegistry
from .tts.factory import make_tts
from .vc.factory import make_vc, vc_status


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
    hud = OrbServer(settings.hud_host, settings.hud_port) if settings.hud_enabled else None

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
    registry.register(make_voice_status_tool(settings))

    # MCP tools via the caller-owned AsyncExitStack (held open for process life).
    if exit_stack is not None:
        mcp_tools, _search = await load_mcp_tools(DEFAULT_MCP_SERVERS, exit_stack)
        for tool in mcp_tools:
            registry.register(tool, gated=True)  # MCP actions are irreversible

    # Default brain = Claude subscription login (no API key/bill); "api" backend uses
    # the registry/confirm tool loop. Both expose respond()/warm() to the orchestrator.
    brain = make_brain(
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
        hud=hud,
    )


def _spawn_overlay(url: str) -> subprocess.Popen | None:
    """Launch the native macOS HUD overlay as its own process (AppKit runloop)."""
    try:
        proc = subprocess.Popen([sys.executable, "-m", "jarvis.hud.overlay_mac", url])
        print("[HUD] 화면 오버레이 실행됨 — 말하면 화면에 자비스 인터페이스가 떠오릅니다.")
        return proc
    except OSError as exc:
        print(f"[HUD] 오버레이 실행 실패(브라우저로 {url} 열어도 됩니다): {exc}")
        return None


async def _amain() -> None:
    # AsyncExitStack stays open for the whole process lifetime (MCP sessions live).
    async with contextlib.AsyncExitStack() as stack:
        orch = await build_orchestrator(exit_stack=stack)
        # Warm models + persona cache before listening.
        orch.stt.warm()
        orch.tts.warm()
        orch.vc.warm()
        await orch.brain.warm()
        _active, voice_msg = vc_status(orch.settings)
        print(f"[음성] {voice_msg}")
        overlay = None
        if orch.hud is not None:
            try:
                orch.hud.start()
                print(f"[HUD] 자비스 HUD: {orch.hud.url}")
                if orch.settings.hud_overlay:
                    overlay = _spawn_overlay(orch.hud.url)
                if orch.settings.hud_open_browser:
                    webbrowser.open(orch.hud.url)
            except OSError as exc:  # port busy etc. — HUD is optional, keep going
                print(f"[HUD] HUD 비활성화(서버 시작 실패): {exc}")
        print("자비스 준비 완료. 오른쪽 옵션 키를 누른 채 말씀하세요. (Ctrl+C로 종료)")
        try:
            await orch.run()
        finally:
            if overlay is not None and overlay.poll() is None:
                overlay.terminate()


def main() -> None:
    # After the first model download, run with HF_HUB_OFFLINE=1 for fully local STT.
    os.environ.setdefault("HF_HUB_OFFLINE", os.environ.get("HF_HUB_OFFLINE", "0"))
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        print("\n종료합니다.")


if __name__ == "__main__":
    main()
