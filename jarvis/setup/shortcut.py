"""배포판: 바탕화면에 자비스 바로가기(아이콘) 생성 — 첫 실행 셋업 UI에서 선택 시 호출.

  • macOS: 실행 중인 JARVIS.app 으로의 심볼릭 링크를 바탕화면에 만든다.
  • Windows: WScript.Shell 로 바탕화면에 JARVIS.lnk(.exe 가리킴 + 아이콘) 생성.
  • 개발 모드(프로즌 아님): 생략(바로가기는 배포판에서만).

모든 인자는 테스트 주입용으로 열려 있다(system/target/desktop/runner)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def app_target() -> Path | None:
    """바로가기가 가리킬 대상 — 프로즌 번들의 .app(맥) 또는 .exe(윈도우). dev면 None."""
    if not getattr(sys, "frozen", False):
        return None
    p = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        for anc in (p, *p.parents):
            if anc.suffix == ".app":
                return anc
    return p


def create_desktop_shortcut(
    *,
    target: str | os.PathLike[str] | None = None,
    desktop: str | os.PathLike[str] | None = None,
    system: str | None = None,
    runner=None,
) -> tuple[bool, str]:
    """바탕화면 바로가기 생성. (성공?, 사용자 메시지)."""
    system = system or sys.platform
    desk = Path(desktop) if desktop else Path.home() / "Desktop"
    tgt = Path(target) if target else app_target()
    if tgt is None:
        return (False, "개발 모드 — 바로가기는 배포판에서만 만듭니다.")
    if not desk.exists():
        return (False, "바탕화면 폴더를 찾을 수 없습니다.")

    if str(system).startswith("darwin"):
        try:
            if tgt.resolve().parent == desk.resolve():
                return (True, "이미 바탕화면에 자비스가 있습니다.")
            link = desk / tgt.name
            if link.is_symlink() or link.exists():
                try:
                    if link.resolve() == tgt.resolve():
                        return (True, "이미 바탕화면에 바로가기가 있습니다.")
                except OSError:
                    pass
                link.unlink()
            os.symlink(tgt, link)
            return (True, f"바탕화면에 '{link.name}' 아이콘을 만들었습니다.")
        except OSError as exc:
            return (False, f"바로가기 생성 실패: {exc}")

    if str(system).startswith("win"):
        lnk = desk / "JARVIS.lnk"
        ps = (
            "$w=New-Object -ComObject WScript.Shell;"
            f"$s=$w.CreateShortcut('{lnk}');"
            f"$s.TargetPath='{tgt}';$s.IconLocation='{tgt}';$s.Save()"
        )
        run = runner or subprocess.run
        try:
            run(["powershell", "-NoProfile", "-Command", ps], check=True)
            return (True, "바탕화면에 'JARVIS' 아이콘을 만들었습니다.")
        except Exception as exc:  # noqa: BLE001
            return (False, f"바로가기 생성 실패: {exc}")

    return (False, "지원하지 않는 운영체제입니다.")
