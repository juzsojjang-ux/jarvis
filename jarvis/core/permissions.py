"""macOS 권한 확인·요청 — 첫 실행(및 권한 미부여 시 매 실행).

서명 없는 배포 빌드는 재빌드마다 TCC 권한(특히 '손쉬운 사용')이 무효화된다. 앱이
권한을 확인·요청하지 않으면, PTT(오른쪽 옵션) 키가 조용히 죽기만 하고 사용자는 이유를
모른다. 그래서 부팅 때마다 필요한 권한을 확인하고, 없으면 시스템 다이얼로그를 띄우고
설정 창을 열어 안내한다 — 절대 조용히 넘어가지 않는다(사용자 요구).

- 손쉬운 사용(Accessibility): PTT 키 입력 모니터링 + cliclick 화면 제어에 필수. 없으면
  AXIsProcessTrustedWithOptions가 시스템 다이얼로그를 띄운다(부여 전까지 매 실행).
- 마이크: STT에 필수지만 sounddevice가 스트림 열 때 OS가 자동으로 묻는다(웨이크워드가
  되면 이미 허용된 것). 여기서는 안내만.
- 화면 녹화(Screen Recording): '화면 봐줘'(capture_screen)에 필요. 평소엔 강제하지 않고
  상태만 확인 — 실제 사용 시 OS가 자동으로 묻는다.

어떤 함수도 예외를 올리지 않는다 — 권한 점검이 부팅을 막으면 안 된다.
"""
from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable


def _is_mac() -> bool:
    return sys.platform == "darwin"


def _ax_api():
    """AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt 를 얻는다.
    ApplicationServices 우선, 없으면 Quartz(둘 다 같은 심볼을 노출)."""
    try:
        from ApplicationServices import (  # type: ignore
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )
        return AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
    except Exception:
        from Quartz import (  # type: ignore
            AXIsProcessTrustedWithOptions,
            kAXTrustedCheckOptionPrompt,
        )
        return AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt


def accessibility_trusted(prompt: bool = False) -> bool:
    """손쉬운 사용(입력 모니터링 — PTT 키) 권한 여부.
    prompt=True면 권한이 없을 때 시스템 다이얼로그('…가 손쉬운 사용으로 제어하려 합니다')를
    띄운다. 부여될 때까지 실행마다 다시 뜬다. API 사용 불가 시 보수적으로 False."""
    if not _is_mac():
        return True
    try:
        ax_trusted, prompt_key = _ax_api()
        return bool(ax_trusted({prompt_key: bool(prompt)}))
    except Exception:  # noqa: BLE001 - 권한 점검 실패가 부팅을 막으면 안 된다
        return False


def screen_capture_trusted() -> bool:
    """화면 녹화 권한 여부(없어도 강제하지 않음 — 화면 기능 사용 시 OS가 자동 요청)."""
    if not _is_mac():
        return True
    try:
        from Quartz import CGPreflightScreenCaptureAccess  # type: ignore
        return bool(CGPreflightScreenCaptureAccess())
    except Exception:  # noqa: BLE001
        return True  # 알 수 없으면 막지 않는다


def open_settings_pane(anchor: str) -> None:
    """시스템 설정의 개인정보 보호 창을 연다(예: Privacy_Accessibility)."""
    if not _is_mac():
        return
    try:
        subprocess.run(
            ["open", f"x-apple.systempreferences:com.apple.preference.security?{anchor}"],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:  # noqa: BLE001
        pass


def ensure_permissions(announce: Callable[[str], None] | None = None) -> dict[str, bool]:
    """부팅 시 필요한 권한을 확인하고 없으면 요청/안내한다.

    - 손쉬운 사용: 없으면 시스템 다이얼로그(prompt) + 설정 창 + 안내 출력/음성.
    - 화면 녹화: 상태만 확인(강제 안 함).
    반환 {"accessibility": bool, "screen": bool}. 예외 없음."""
    if not _is_mac():
        return {"accessibility": True, "screen": True}
    try:
        return _ensure_permissions_mac(announce)
    except Exception as exc:  # noqa: BLE001 - 권한 점검이 부팅을 막거나 깨면 안 된다
        print(f"[권한] 점검 중 오류(계속 진행): {exc}")
        return {"accessibility": False, "screen": True}


def _ensure_permissions_mac(announce: Callable[[str], None] | None) -> dict[str, bool]:
    acc = accessibility_trusted(prompt=True)  # 없으면 여기서 시스템 다이얼로그가 뜬다
    scr = screen_capture_trusted()
    if not acc:
        print("[권한] ⚠ 손쉬운 사용(접근성) 권한이 필요합니다 — 오른쪽 옵션(PTT) 키와 "
              "화면 제어가 동작하려면, 방금 열린 시스템 설정 > 개인정보 보호 및 보안 > "
              "손쉬운 사용에서 'JARVIS'를 켠 뒤 자비스를 다시 실행하세요. "
              "(웨이크워드 '자비스'는 권한 없이도 됩니다.)")
        open_settings_pane("Privacy_Accessibility")
        if announce is not None:
            try:
                announce("손쉬운 사용 권한이 필요합니다. 시스템 설정을 열었으니 자비스를 "
                         "허용하고 다시 실행해 주세요. 그동안은 자비스라고 부르시면 됩니다.")
            except Exception:  # noqa: BLE001
                pass
    else:
        print("[권한] 손쉬운 사용 권한 OK.")
    if not scr:
        print("[권한] (참고) 화면 녹화 권한은 아직 없습니다 — '화면 봐줘'를 쓰실 때 "
              "OS가 자동으로 요청합니다.")
    return {"accessibility": acc, "screen": scr}
