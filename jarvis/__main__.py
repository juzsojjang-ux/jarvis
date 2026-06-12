from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import subprocess
import sys
import webbrowser

from anthropic import AsyncAnthropic

from .activation.ptt import PushToTalk
from .audio.capture import MicCapture
from .audio.micstream import MicStream
from .audio.playback import Playback
from .audio.wake import build_wake
from .brain.factory import make_brain
from .brain.memory import MemoryStore
from .brain.persona import load_persona
from .brain.sentence import SentenceChunker
from .core.config import Settings
from .core.orchestrator import Orchestrator
from .core.platform_defaults import apply_platform_defaults
from .hud.orb_server import OrbServer
from .proactive.engine import ProactiveEngine
from .proactive.monitors import build_monitors
from .proactive.timers import DEFAULT_BOARD
from .stt.factory import make_stt
from .tools.builtin.local_tools import calc, make_remember_tool
from .tools.builtin.time_weather import get_time, get_weather
from .tools.builtin.voice_status import make_voice_status_tool
from .tools.builtin.web_search import WEB_SEARCH_TOOL
from .tools.confirm import VoiceConfirm
from .tools.mcp_client import DEFAULT_MCP_SERVERS, load_mcp_tools
from .tools.registry import ToolRegistry
from .tts.factory import make_tts
from .vc.factory import make_vc, vc_status
from .remote.server import RemoteServer
from .remote.token import load_or_create_token


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
    apply_platform_defaults(settings)
    memory = MemoryStore(settings.memory_path)
    memory.load()
    persona = load_persona(settings.persona_path)  # real >=4096-token persona; no fallback
    if settings.assistant_name and settings.assistant_name != "자비스":
        # 이름 변경(첫 설정) — 모든 두뇌가 같은 페르소나를 받으므로 여기 한 곳에서.
        persona += (f"\n\n[이름 변경] 당신의 이름은 이제 '{settings.assistant_name}'이다. "
                    f"'자비스' 대신 '{settings.assistant_name}'로 자칭하고, 사용자가 "
                    f"'{settings.assistant_name}'라고 부르면 응답한다. 그 외 인격·규칙은 동일하다.")

    # Shared backends (constructed here, then dependency-injected).
    activator = PushToTalk(settings.ptt_key)
    micstream = MicStream(sample_rate=16000)
    capture = MicCapture(micstream)
    stt = make_stt(settings)
    tts = make_tts(settings)
    vc = make_vc(settings)
    playback = Playback(sample_rate=settings.playback_rate)
    chunker = SentenceChunker()
    hud = OrbServer(settings.hud_host, settings.hud_port) if settings.hud_enabled else None
    wake = build_wake(settings, micstream) if settings.wake_enabled else None

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

    orch = Orchestrator(
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
        micstream=micstream,
        wake=wake,
    )
    if settings.proactive_enabled:
        orch.proactive = ProactiveEngine(
            build_monitors(settings, timers=DEFAULT_BOARD),
            announce=orch.announce,
            can_speak=orch._can_announce,
            cooldown_s=settings.proactive_cooldown_min * 60,
            cooldown_overrides={"timer_done": 0.0},  # 연속 타이머는 정상 동작
        )
    return orch


def _child_cmd(module: str, *args: str) -> list[str]:
    """자식 프로세스(오버레이/트레이) 실행 커맨드. PyInstaller frozen 번들에서는
    sys.executable이 자비스 본체 EXE라 `-m`이 무시되고 본체가 통째로 또 떠
    무한 증식한다 — 런처(jarvis_launch)가 해석하는 --child= 플래그로 디스패치한다."""
    if getattr(sys, "frozen", False):
        return [sys.executable, f"--child={module}", *args]
    return [sys.executable, "-m", module, *args]


def _spawn_overlay(url: str) -> subprocess.Popen | None:
    """HUD 오버레이를 자체 프로세스로 띄운다 — 맥은 네이티브 WKWebView 오버레이,
    윈도우는 전용 창(pywebview→Edge 앱 모드). 둘 다 브라우저 탭이 아니다."""
    module = ("jarvis.hud.overlay_win" if sys.platform.startswith("win")
              else "jarvis.hud.overlay_mac")
    try:
        proc = subprocess.Popen(_child_cmd(module, url))
        print("[HUD] 화면 오버레이 실행됨 — 말하면 화면에 자비스 인터페이스가 떠오릅니다.")
        return proc
    except OSError as exc:
        print(f"[HUD] 오버레이 실행 실패(브라우저로 {url} 열어도 됩니다): {exc}")
        return None


def _spawn_tray() -> subprocess.Popen | None:
    """'자비스 실행 중' 상태 아이콘을 자체 프로세스로 띄운다 — 맥 메뉴 막대 / 윈도우
    트레이. 부모 PID를 넘겨 트레이 '종료' 메뉴가 자비스를 끌 수 있게 한다."""
    try:
        proc = subprocess.Popen(_child_cmd("jarvis.hud.tray", str(os.getpid())))
        print("[상태] 메뉴 막대/트레이에 '자비스 실행 중' 아이콘을 띄웠습니다.")
        return proc
    except OSError as exc:
        print(f"[상태] 상태 아이콘 실행 실패(무시): {exc}")
        return None


def _install_exit_signals(loop, task) -> None:
    """SIGTERM/SIGHUP을 우아한 취소로 변환 — 단, 있는 플랫폼에서만. Windows에는
    SIGHUP 자체가 없고(AttributeError) add_signal_handler도 NotImplementedError라
    둘 다 조용히 건너뛴다(Ctrl+C는 KeyboardInterrupt로 이미 우아하게 끝난다)."""
    for _name in ("SIGTERM", "SIGHUP"):
        _sig = getattr(signal, _name, None)
        if _sig is None:
            continue
        with contextlib.suppress(NotImplementedError, ValueError, RuntimeError):
            loop.add_signal_handler(_sig, task.cancel)


def _acquire_singleton():
    """로컬 포트 바인드로 단일 인스턴스 보장. 중복 부팅(더블클릭 두 번, 자식 디스패치
    사고)이 포트 충돌·프로세스 증식으로 번지는 걸 원천 차단한다. 반환된 소켓을
    프로세스 수명 동안 들고 있어야 잠금이 유지된다. 이미 떠 있으면 None."""
    import socket
    port = int(os.environ.get("JARVIS_SINGLETON_PORT", "48799"))
    if port == 0:  # 0 = 잠금 비활성(테스트/특수용)
        return socket.socket()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
    except OSError:
        s.close()
        return None
    return s


async def _amain() -> None:
    _singleton = _acquire_singleton()  # 수명: _amain 전체 (지역변수로 유지)
    if _singleton is None:
        print("[부팅] 자비스가 이미 실행 중입니다 — 중복 실행을 끝냅니다.")
        return
    # 첫 실행 설정 — 설정 파일이 없거나 미완료이면 브라우저 설정 UI를 띄운다.
    # JARVIS_BRAIN_PROVIDER 환경변수가 이미 설정돼 있으면(CI/headless) UI 블록 건너뜀.
    from jarvis.setup.store import apply_setup_env, configured_provider, is_configured
    if not is_configured() and not os.environ.get("JARVIS_BRAIN_PROVIDER"):
        from jarvis.setup.launcher import run_first_run_setup
        print("[설정] 첫 실행 — 브라우저에서 두뇌(Claude/Gemini/GPT)를 선택하세요.")
        run_first_run_setup()
    os.environ.setdefault("JARVIS_BRAIN_PROVIDER", configured_provider() or "claude")
    apply_setup_env()  # 첫 설정의 보이스/이름 선택 → env (사용자 env가 우선)

    # AsyncExitStack stays open for the whole process lifetime (MCP sessions live).
    async with contextlib.AsyncExitStack() as stack:
        orch = await build_orchestrator(exit_stack=stack)
        # Warm models + persona cache before listening.
        orch.stt.warm()
        orch.tts.warm()
        orch.vc.warm()
        # 두뇌 예열 실패(CLI 미설치/미로그인 등)는 부팅을 막지 않는다 — 실제 대화
        # 턴에서 같은 오류가 나면 오케스트레이터가 음성/패널로 알린다.
        warm_results = await asyncio.gather(
            orch.brain.warm(), orch.warm_phrases(), return_exceptions=True
        )
        for exc in warm_results:
            if isinstance(exc, BaseException):
                print(f"[두뇌] 예열 실패(부팅은 계속합니다): {exc}")
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
        tray = None
        if getattr(orch.settings, "tray_enabled", True):
            tray = _spawn_tray()
        remote = None
        if orch.settings.remote_enabled:
            try:
                loop = asyncio.get_running_loop()

                def _remote_bridge(text: str) -> dict:
                    fut = asyncio.run_coroutine_threadsafe(orch.remote_turn(text), loop)
                    try:
                        # 검색·도구 다중 호출 턴은 2분을 넘길 수 있다 — 4분까지 허용.
                        return fut.result(timeout=240.0)
                    except TimeoutError:
                        # 두뇌 작업을 취소해야 _remote_busy가 풀린다 — 안 풀면
                        # 타임아웃 한 번에 이후 모든 원격 턴이 busy에 갇힌다.
                        fut.cancel()
                        raise

                remote = RemoteServer(_remote_bridge, orch.settings.remote_host,
                                      orch.settings.remote_port, load_or_create_token())
                remote.start()
                print(f"[원격] 아이폰 단축어 수신: {remote.url} "
                      "(토큰: ~/.jarvis/remote_token · 설정법: docs/REMOTE.md)")
            except OSError as exc:  # 포트 사용 중 등 — 원격은 옵션, 부팅은 계속
                print(f"[원격] 시작 실패(비활성화): {exc}")
        if orch.wake is not None:
            print('자비스 준비 완료. "자비스"라고 부르거나, 오른쪽 옵션 키를 누른 채 '
                  "말씀하세요. (Ctrl+C로 종료)")
        else:
            print("자비스 준비 완료. 오른쪽 옵션 키를 누른 채 말씀하세요. (Ctrl+C로 종료)")
        if orch.proactive is not None:
            from time import monotonic

            from .proactive.events import Announcement
            now = monotonic()
            # 부팅 인사 — 화면이 이미 해제 상태면 SessionMonitor의 첫 브리핑이 이걸
            # 대체한다(enqueue 규칙). 엔진과 같은 단조시계 사용.
            orch.proactive.enqueue(Announcement(
                "boot_greet", "자비스가 방금 기동했다 — 시스템 정상임을 짧게 보고하며 인사",
                3, now, now + 300))
        # SIGTERM(트레이 '종료'·kill)·SIGHUP(터미널 닫힘)에도 finally가 돌게 우아한
        # 종료로 변환한다 — 기본 동작(즉사)은 오버레이/트레이를 유령으로 남겼다.
        me = asyncio.current_task()
        loop = asyncio.get_running_loop()
        _install_exit_signals(loop, me)
        try:
            await orch.run()
        except asyncio.CancelledError:
            print("\n종료 신호 수신 — 정리 후 종료합니다.")
        finally:
            if overlay is not None and overlay.poll() is None:
                overlay.terminate()
            if tray is not None and tray.poll() is None:
                tray.terminate()
            if remote is not None:
                remote.stop()


def main() -> None:
    # After the first model download, run with HF_HUB_OFFLINE=1 for fully local STT.
    os.environ.setdefault("HF_HUB_OFFLINE", os.environ.get("HF_HUB_OFFLINE", "0"))
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        print("\n종료합니다.")


if __name__ == "__main__":
    main()
