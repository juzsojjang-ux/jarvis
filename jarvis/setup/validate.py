"""프로바이더 키 검증 — 작은 테스트 호출. 클라이언트 주입 가능(테스트는 가짜)."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any


def _default_codex_check() -> bool:
    from jarvis.brain.codex_auth import is_codex_logged_in
    return is_codex_logged_in()


def _default_claude_check() -> bool:
    from jarvis.setup.login import claude_logged_in
    return claude_logged_in()


async def validate(
    provider: str,
    key: str,
    *,
    gemini_client: Any = None,
    openai_client: Any = None,
    codex_check: Callable[[], bool] | None = None,
    claude_check: Callable[[], bool] | None = None,
) -> tuple[bool, str]:
    provider = (provider or "").strip()

    if provider == "claude":
        # 로그인 안 된 채 '시작'을 누르면 '설정 완료'로 통과해버려 두뇌가 먹통이
        # 되고 다음 부팅에 첫실행이 또 뜬다(거짓 완료). 로그인 완료만 통과시킨다.
        check = claude_check or _default_claude_check
        if check():
            return True, "Claude 구독으로 사용합니다."
        return False, "먼저 'Claude 로그인' 버튼으로 로그인을 완료한 뒤 다시 시작하세요."

    if provider == "gemini":
        if not key.strip():
            return False, "Gemini API 키를 입력하세요."
        try:
            client = gemini_client
            if client is None:
                from google import genai  # type: ignore[import]

                client = genai.Client(api_key=key)
            # 타임아웃 필수: 네트워크 행(hang) 시 설정 화면이 무한 대기하던 것 방지(audit medium).
            await asyncio.wait_for(
                client.aio.models.generate_content(model="gemini-2.5-flash", contents="hi"),
                timeout=15,
            )
            return True, "Gemini 키가 확인되었습니다."
        except asyncio.TimeoutError:
            return False, "Gemini 키 확인 시간이 초과됐습니다(네트워크를 확인해 주세요)."
        except Exception:  # noqa: BLE001
            return False, "Gemini 키가 올바르지 않습니다."

    if provider == "gpt":
        check = codex_check or _default_codex_check
        if check():
            return True, "ChatGPT 구독(codex) 로그인이 확인되었습니다."
        return False, "먼저 터미널에서 `codex login` 을 실행해 ChatGPT로 로그인하세요."

    return False, "알 수 없는 프로바이더입니다."
