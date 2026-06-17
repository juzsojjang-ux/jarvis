"""자비스 자가진단 — "뭐가 문제인지"를 스스로 점검해 보고한다.

설계 원칙:
  - 어떤 점검도 절대 raise하지 않는다(진단이 새 장애를 만들면 안 된다).
  - 오케스트레이터 없이도 돈다(두뇌 도구 경로) — orch가 있으면 더 깊이 본다.
  - 외부 접근(파일/장치)은 전부 주입 가능해 테스트가 쉽다.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

LOG_DIR = Path.home() / ".jarvis" / "logs"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def _check_mic() -> Check:
    try:
        import sounddevice as sd  # noqa: PLC0415
        ins = [d for d in sd.query_devices() if d.get("max_input_channels", 0) > 0]
        if ins:
            return Check("마이크", True, f"입력 장치 {len(ins)}개")
        return Check("마이크", False, "입력 장치가 없습니다 — 마이크 연결/권한을 확인하세요")
    except Exception as exc:  # noqa: BLE001
        return Check("마이크", False, f"오디오 장치 조회 실패: {exc}")


def _check_crash_log(now: datetime | None = None, log_dir: Path | None = None) -> Check:
    d = log_dir or LOG_DIR
    f = d / "crash.log"
    if not f.exists():
        return Check("크래시 기록", True, "크래시 기록 없음")
    try:
        today = (now or datetime.now()).strftime("%Y-%m-%d")
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        todays = [ln for ln in lines if ln.startswith("=== CRASH ") and today in ln]
        # faulthandler가 쓰는 네이티브 크래시(세그폴트 등)는 '=== CRASH ' 마커가 없다 —
        # 'Fatal Python error' 시그니처도 센다(audit r3 low: 네이티브 크래시를 놓치던 것).
        native = [ln for ln in lines if "Fatal Python error" in ln]
        if todays or native:
            parts = []
            if todays:
                parts.append(f"오늘 강제종료 {len(todays)}회(마지막 {todays[-1][10:29]})")
            if native:
                parts.append(f"네이티브 크래시 {len(native)}건")
            return Check("크래시 기록", False, " · ".join(parts))
        return Check("크래시 기록", True, "오늘 크래시 없음")
    except Exception as exc:  # noqa: BLE001
        return Check("크래시 기록", False, f"crash.log 읽기 실패: {exc}")


def _check_error_log(log_dir: Path | None = None) -> Check:
    f = (log_dir or LOG_DIR) / "jarvis.log"
    if not f.exists():
        return Check("오류 로그", True, "실행 로그 없음(개발 모드)")
    try:
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        # 현재 세션만 본다 — 마지막 'JARVIS start' 마커 이후. 이전 실행(이미 고쳐진)의
        # 오류가 건강한 이번 세션을 오탐으로 빨갛게 만들지 않게 한다.
        start = 0
        for i in range(len(lines) - 1, -1, -1):
            if "JARVIS start" in lines[i]:
                start = i
                break
        session = lines[start:]
        errs = [ln for ln in session if "[오류]" in ln or "예열 실패" in ln]
        if errs:
            return Check("오류 로그", False,
                         f"이번 세션 오류 {len(errs)}건 — 마지막: {errs[-1].strip()[:80]}")
        return Check("오류 로그", True, "이번 세션 로그에 오류 없음")
    except Exception as exc:  # noqa: BLE001
        return Check("오류 로그", False, f"jarvis.log 읽기 실패: {exc}")


def _check_skills() -> Check:
    try:
        from ..tools.skills import load_skill_tools  # noqa: PLC0415
        n = len(load_skill_tools())
        return Check("자작 스킬", True, f"{n}개 로드됨")
    except Exception as exc:  # noqa: BLE001
        return Check("자작 스킬", False, f"스킬 로드 실패: {exc}")


def _check_external_mcp() -> Check:
    try:
        from ..tools.external_mcp import load_external_servers  # noqa: PLC0415
        servers = load_external_servers()
        if servers:
            return Check("외부 MCP", True, f"{len(servers)}개 연결 설정: {', '.join(servers)}")
        return Check("외부 MCP", True, "설정 없음(선택 사항)")
    except Exception as exc:  # noqa: BLE001
        return Check("외부 MCP", False, f"~/.jarvis/mcp.json 로드 실패: {exc}")


def _check_disk() -> Check:
    try:
        free_gb = shutil.disk_usage(Path.home()).free / 1e9
        if free_gb < 5:
            return Check("디스크", False, f"남은 공간 {free_gb:.1f}GB — 5GB 미만")
        return Check("디스크", True, f"남은 공간 {free_gb:.0f}GB")
    except Exception as exc:  # noqa: BLE001
        return Check("디스크", False, f"확인 실패: {exc}")


def _check_consultants() -> Check:
    try:
        from ..brain.consult import available  # noqa: PLC0415
        avail = available()
        ons = [k for k, v in avail.items() if v]
        if ons:
            return Check("보조 두뇌", True, f"자문 가능: {', '.join(ons)}")
        return Check("보조 두뇌", True, "자문 가능한 보조 두뇌 없음(키/로그인 없음 — 선택 사항)")
    except Exception as exc:  # noqa: BLE001
        return Check("보조 두뇌", False, f"확인 실패: {exc}")


def _orch_checks(orch) -> list[Check]:
    out: list[Check] = []
    try:
        brain = getattr(orch, "brain", None)
        name = type(brain).__name__ if brain is not None else "없음"
        last_err = getattr(brain, "last_error", None)
        if brain is None:
            out.append(Check("두뇌", False, "두뇌가 연결되지 않았습니다"))
        elif last_err:
            out.append(Check("두뇌", False, f"{name} — 마지막 오류: {str(last_err)[:80]}"))
        else:
            out.append(Check("두뇌", True, name))
    except Exception as exc:  # noqa: BLE001
        out.append(Check("두뇌", False, f"확인 실패: {exc}"))
    try:
        from ..vc.factory import vc_status  # noqa: PLC0415
        _active, msg = vc_status(orch.settings)
        out.append(Check("음성", True, msg[:90]))
    except Exception as exc:  # noqa: BLE001
        out.append(Check("음성", False, f"확인 실패: {exc}"))
    try:
        hud = getattr(orch, "hud", None)
        if hud is not None and getattr(hud, "url", None):
            out.append(Check("HUD", True, str(hud.url)))
        else:
            out.append(Check("HUD", True, "비활성(설정)"))
    except Exception as exc:  # noqa: BLE001
        out.append(Check("HUD", False, f"확인 실패: {exc}"))
    try:
        usage = getattr(orch, "usage", None)
        if usage is not None:
            out.append(Check("사용량", True, usage.summary()[:90]))
    except Exception:  # noqa: BLE001
        pass
    return out


def run_checks(orch=None, *, now: datetime | None = None,
               log_dir: Path | None = None) -> list[Check]:
    """전체 자가진단. orch가 있으면 두뇌/음성/HUD까지 들여다본다."""
    checks: list[Check] = []
    if orch is not None:
        checks += _orch_checks(orch)
    for probe in (_check_mic, _check_consultants, _check_skills,
                  _check_external_mcp, _check_disk):
        try:
            checks.append(probe())
        except Exception as exc:  # noqa: BLE001 - 프로브 자체가 죽어도 진단은 계속
            checks.append(Check(probe.__name__, False, f"점검 실패: {exc}"))
    try:
        checks.append(_check_crash_log(now=now, log_dir=log_dir))
        checks.append(_check_error_log(log_dir=log_dir))
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("로그", False, f"점검 실패: {exc}"))
    return checks


def format_report(checks: list[Check]) -> str:
    """패널용 상세 보고(한국어, 줄 단위)."""
    lines = ["자가진단 보고"]
    for c in checks:
        mark = "✓" if c.ok else "✗"
        lines.append(f"{mark} {c.name}: {c.detail}")
    bad = [c for c in checks if not c.ok]
    if bad:
        lines.append("")
        lines.append(f"이상 {len(bad)}건 — 위 ✗ 항목을 확인하세요.")
    else:
        lines.append("")
        lines.append("모든 항목 정상입니다.")
    return "\n".join(lines)


def summary_line(checks: list[Check]) -> str:
    """음성용 한 줄 요약(한국어)."""
    bad = [c for c in checks if not c.ok]
    if not bad:
        return f"점검 완료 — {len(checks)}개 항목 모두 정상입니다."
    names = ", ".join(c.name for c in bad[:3])
    more = "" if len(bad) <= 3 else f" 외 {len(bad) - 3}건"
    return f"점검 완료 — {len(checks)}개 중 {len(bad)}개 이상: {names}{more}."
