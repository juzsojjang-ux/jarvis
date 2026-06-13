"""HUD 실시간 텔레메트리 — 진짜 데이터만(가짜 장식 금지). 순수 collect()는 입력→패널 dict
리스트로 단위 테스트가 쉽고, TelemetryProvider가 주기적으로 샘플링해 OrbHub에 push한다."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable


def collect(*, clock: str, mic_on: bool, task_count: int,
            cpu: int | None = None, mem: int | None = None,
            net: bool | None = None) -> list[dict]:
    """텔레메트리 패널 목록. 데이터 없는 항목은 생략(Kent Seki '기능 없으면 뺀다')."""
    items: list[dict] = [
        {"id": "clock", "title": f"◷ {clock}", "body": "", "kind": "telemetry", "tone": "cyan"},
        {"id": "mic", "title": "◇ 입력", "kind": "telemetry", "tone": "cyan",
         "body": "MIC ● LIVE" if mic_on else "MIC ○ 대기"},
    ]
    if net is not None:
        items.append({"id": "net", "title": "◇ NET", "kind": "telemetry", "tone": "cyan",
                      "body": "TAILSCALE ✓" if net else "OFFLINE ✕"})
    if cpu is not None and mem is not None:
        items.append({"id": "sys", "title": "◰ SYS LOAD", "kind": "telemetry", "tone": "gold",
                      "body": f"CPU {cpu}% · MEM {mem}%",
                      "gauge": {"cpu": int(cpu), "mem": int(mem)}})
    if task_count > 0:
        items.append({"id": "tasks", "title": "◳ 작업", "kind": "telemetry", "tone": "gold",
                      "body": f"백그라운드 {task_count}건"})
    return items


def _sample_cpu_mem() -> tuple[int | None, int | None]:
    """psutil 있으면 CPU/MEM(%) 정수, 없으면 (None, None) — 게이지 생략."""
    try:
        import psutil  # 선택 의존성
    except Exception:
        return (None, None)
    try:
        return (int(psutil.cpu_percent(interval=None)), int(psutil.virtual_memory().percent))
    except Exception:
        return (None, None)


class TelemetryProvider:
    """주기적으로 텔레메트리를 수집해 hub.publish_telemetry로 push하는 데몬 스레드.
    state_fn()은 오케스트레이터가 제공: {'mic_on': bool, 'task_count': int, 'net': bool|None} 반환."""

    def __init__(self, hub, state_fn: Callable[[], dict], interval: float = 2.0,
                 clock_fn: Callable[[], str] | None = None) -> None:
        self._hub = hub
        self._state_fn = state_fn
        self._interval = interval
        self._clock_fn = clock_fn or (lambda: time.strftime("%H:%M"))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                st = self._state_fn() or {}
                cpu, mem = _sample_cpu_mem()
                items = collect(clock=self._clock_fn(), mic_on=bool(st.get("mic_on")),
                                task_count=int(st.get("task_count", 0)), cpu=cpu, mem=mem,
                                net=st.get("net"))
                self._hub.publish_telemetry(items)
            except Exception:  # 텔레메트리가 HUD/음성을 깨면 안 된다
                pass
            self._stop.wait(self._interval)

    def stop(self) -> None:
        self._stop.set()
        self._thread = None
