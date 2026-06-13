"""첫 설정 — 프로바이더 로그인 흐름.

UI에서 카드(클로드/GPT)를 고르면 버튼 한 번으로 OAuth 브라우저를 열고, 완료를
자동 감지한다. 사용자가 터미널에 명령을 칠 필요가 없다. 외부 호출(서브프로세스/
파일)은 전부 주입 가능 — 테스트는 가짜로 대체한다. 절대 raise하지 않는다.

- claude: `claude auth login`(브라우저) → `claude auth status`의 loggedIn 폴링
- gpt   : `codex login`(설치돼 있으면) → ~/.codex/auth.json 폴링
- gemini: OAuth 불가(구글 정책) → 키 입력 방식 유지(여기선 다루지 않음)
"""
from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

OAUTH_PROVIDERS = ("claude", "gpt")


# ----- 상태 확인 -------------------------------------------------------------
def claude_logged_in(runner: Callable = subprocess.run) -> bool:
    try:
        res = runner(["claude", "auth", "status"], capture_output=True,
                     text=True, timeout=15)
        out = getattr(res, "stdout", "") or ""
        data = json.loads(out[out.index("{"):out.rindex("}") + 1])
        return bool(data.get("loggedIn"))
    except Exception:  # noqa: BLE001 - 미설치/미로그인/파싱실패 전부 '아님'
        return False


def gpt_logged_in(checker: Callable[[], bool] | None = None) -> bool:
    try:
        if checker is not None:
            return bool(checker())
        from jarvis.brain.codex_auth import is_codex_logged_in
        return bool(is_codex_logged_in())
    except Exception:  # noqa: BLE001
        return False


def login_status(provider: str, *, runner: Callable = subprocess.run,
                 checker: Callable[[], bool] | None = None) -> bool:
    p = (provider or "").strip()
    if p == "claude":
        return claude_logged_in(runner)
    if p == "gpt":
        return gpt_logged_in(checker)
    return False


# ----- 로그인 시작(브라우저 OAuth) -------------------------------------------
def _has(cmd: str, which: Callable[[str], Any] = shutil.which) -> bool:
    return which(cmd) is not None


def start_login(provider: str, *, spawn: Callable = subprocess.Popen,
                which: Callable[[str], Any] = shutil.which) -> tuple[bool, str]:
    """OAuth 로그인 프로세스를 백그라운드로 띄운다(브라우저가 열린다).
    (시작됨?, 사용자 안내 메시지)."""
    p = (provider or "").strip()
    if p == "claude":
        if not _has("claude", which):
            return False, ("claude 명령을 찾을 수 없습니다. 터미널에서 "
                           "`curl -fsSL https://claude.ai/install.sh | bash` 로 설치 후 "
                           "다시 시도하세요.")
        if claude_logged_in():
            return True, "이미 Claude에 로그인되어 있습니다."
        try:
            spawn(["claude", "auth", "login"],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:  # noqa: BLE001
            return False, f"로그인 실행 실패: {exc}"
        return True, "브라우저에서 Claude 로그인을 진행하세요 — 끝나면 자동으로 인식합니다."
    if p == "gpt":
        if gpt_logged_in():
            return True, "이미 ChatGPT(codex)에 로그인되어 있습니다."
        if not _has("codex", which):
            return False, ("codex 명령이 없습니다. 터미널에서 "
                           "`npm i -g @openai/codex` 설치 후 `codex login` 을 실행하세요.")
        try:
            spawn(["codex", "login"],
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:  # noqa: BLE001
            return False, f"로그인 실행 실패: {exc}"
        return True, "브라우저에서 ChatGPT 로그인을 진행하세요 — 끝나면 자동으로 인식합니다."
    return False, "이 프로바이더는 로그인 버튼을 지원하지 않습니다(키 입력 방식)."
