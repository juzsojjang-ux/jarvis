"""부모 프로세스 감시 — 메인 자비스가 죽으면(정상 종료든 kill -9든 크래시든)
오버레이/트레이 같은 보조 UI 프로세스가 스스로 종료한다.

메인의 finally(terminate)는 SIGKILL·크래시·SIGTERM 즉사에서는 돌지 않는다 —
그때 고아가 된 오버레이가 화면에 유령 HUD/패널로 남았다(실사용 버그). 이 모듈이
백업: 부모가 사라지면 2초 안에 자기를 끝낸다."""
from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable


def pid_alive(pid) -> bool:
    """해당 PID 프로세스가 살아있는가 — 플랫폼 안전.

    주의: 윈도우의 os.kill(pid, 0)은 신호 0이어도 TerminateProcess를 호출해
    **프로세스를 죽인다**(CPython 동작). 반드시 ctypes로 핸들만 열어 확인한다.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        import ctypes
        SYNCHRONIZE = 0x00100000
        WAIT_TIMEOUT = 0x00000102
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(SYNCHRONIZE, False, pid)
        if not h:
            return False
        try:
            return k32.WaitForSingleObject(h, 0) == WAIT_TIMEOUT  # 타임아웃=생존
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)  # 유닉스: 신호 0 = 존재 확인만
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 살아있지만 권한 없음
    except OSError:
        return False


def watch_parent(
    parent_pid: int | str | None = None,
    on_dead: Callable[[], None] | None = None,
    *,
    interval_s: float = 2.0,
    alive: Callable[[], bool] | None = None,
) -> threading.Thread:
    """데몬 스레드로 부모 생존을 감시, 죽으면 on_dead() (기본: 즉시 프로세스 종료).

    parent_pid가 없으면 유닉스 고아 판정(getppid()==1)을 쓴다. ``alive``는 테스트
    주입용 생존 판정 함수.
    """
    cb = on_dead or (lambda: os._exit(0))

    def _alive() -> bool:
        if alive is not None:
            return alive()
        if parent_pid is not None:
            return pid_alive(parent_pid)
        return os.getppid() != 1  # 부모가 죽으면 init(1)으로 재입양된다

    def _loop() -> None:
        while _alive():
            time.sleep(interval_s)
        try:
            cb()
        except Exception:  # noqa: BLE001 - 종료 콜백 실패 시 강제 종료
            os._exit(0)

    t = threading.Thread(target=_loop, daemon=True, name="parent-watch")
    t.start()
    return t
