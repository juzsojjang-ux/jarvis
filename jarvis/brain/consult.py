"""보조 두뇌 자문 — 메인 두뇌가 다른 LLM(제미나이/GPT)에게 단일 질문을 보낸다.

용도: 교차검증("교차 검증해줘"), 세컨드 오피니언("제미나이 생각은?"),
중요한 사실 판단 보강. 무거운 에이전트 루프가 아니라 도구 없는 1회 질의만 —
보조 두뇌가 이 컴퓨터를 조작하는 일은 없다.

절대 raise하지 않는다 — 실패는 한국어 안내 문자열로 돌려준다(도구 경로 안전).
"""
from __future__ import annotations

import asyncio
from typing import Any

_SYS = (
    "You are a consulted expert model giving a second opinion to JARVIS, "
    "a Korean voice assistant. Answer concisely and substantively in Korean. "
    "If you are uncertain, say so explicitly instead of guessing."
)

PROVIDERS = ("gemini", "gpt")

_gpt_brain: Any = None  # 게으른 캐시 — 첫 자문 후 재사용(코덱스 토큰 갱신 포함)


def _settings():
    from ..core.config import Settings  # noqa: PLC0415
    return Settings()


def available() -> dict[str, bool]:
    """자문 가능한 보조 두뇌 — 자격증명 존재만 본다(네트워크 안 탐)."""
    out: dict[str, bool] = {}
    try:
        from .gemini import _gemini_key  # noqa: PLC0415
        out["gemini"] = bool(_gemini_key(_settings()))
    except Exception:  # noqa: BLE001
        out["gemini"] = False
    try:
        from .codex_auth import is_codex_logged_in  # noqa: PLC0415
        out["gpt"] = bool(is_codex_logged_in())
    except Exception:  # noqa: BLE001
        out["gpt"] = False
    return out


async def _consult_gemini(question: str, settings: Any, client: Any = None) -> str:
    from .gemini import _gemini_key  # noqa: PLC0415
    key = _gemini_key(settings)
    if client is None:
        if not key:
            return ("제미나이 자문 불가 — API 키가 없습니다. "
                    "첫 실행 설정에서 키를 넣으면 활성화됩니다.")
        from google import genai  # noqa: PLC0415
        client = genai.Client(api_key=key)
    from google.genai import types as gtypes  # noqa: PLC0415
    model = getattr(settings, "gemini_model", None) or "gemini-2.5-flash"
    resp = await client.aio.models.generate_content(
        model=model, contents=question,
        config=gtypes.GenerateContentConfig(system_instruction=_SYS))
    parts = resp.candidates[0].content.parts
    return "".join(p.text for p in parts if getattr(p, "text", None)).strip()


async def _consult_gpt(question: str, settings: Any, brain: Any = None) -> str:
    global _gpt_brain
    if brain is None:
        if _gpt_brain is None:
            from .codex_auth import is_codex_logged_in  # noqa: PLC0415
            from .openai_brain import _gpt_key  # noqa: PLC0415
            # settings.openai_api_key는 존재하지 않는 필드라 키 보유자도 '자문 불가' 오판하던
            # 것을 수정(audit medium): 실제 키 해석기(gpt_api_key→keyring)를 쓴다.
            has_key = bool(_gpt_key(settings))
            if not is_codex_logged_in() and not has_key:
                return ("GPT 자문 불가 — ChatGPT(codex) 로그인이나 API 키가 없습니다. "
                        "터미널에서 `codex login` 하면 활성화됩니다.")
            from .memory import MemoryStore  # noqa: PLC0415
            from .openai_brain import GPTBrain  # noqa: PLC0415
            mem = MemoryStore(settings.memory_path)
            mem.load()
            _gpt_brain = GPTBrain(settings, mem, _SYS, confirm=None)
        brain = _gpt_brain
    client = await brain._ensure_client()
    if brain._auth_mode == "subscription":
        out, _calls = await brain._collect_response(
            client, model=brain._sub_model, instructions=_SYS,
            input=[{"role": "user", "content": question}])
        return (out or "").strip()
    resp = await client.chat.completions.create(
        model=brain._model,
        messages=[{"role": "system", "content": _SYS},
                  {"role": "user", "content": question}])
    return (resp.choices[0].message.content or "").strip()


async def consult(provider: str, question: str, *, timeout_s: float = 90.0,
                  settings: Any = None, _impl: Any = None) -> str:
    """provider("gemini"|"gpt")에게 question을 묻고 한국어 답을 돌려준다."""
    p = (provider or "").strip().lower()
    if p in ("클로드", "claude"):
        return "클로드는 지금 대화 중인 메인 두뇌입니다 — 제가 직접 답합니다."
    if p in ("제미나이", "gemini", "google"):
        p = "gemini"
    elif p in ("지피티", "gpt", "챗gpt", "chatgpt", "openai"):
        p = "gpt"
    else:
        return f"모르는 보조 두뇌입니다: {provider!r} (gemini 또는 gpt)"
    if not (question or "").strip():
        return "질문이 비어 있습니다."
    settings = settings or _settings()
    fn = _impl or (_consult_gemini if p == "gemini" else _consult_gpt)
    try:
        return await asyncio.wait_for(fn(question, settings), timeout=timeout_s)
    except TimeoutError:
        return f"{p} 자문이 {int(timeout_s)}초 안에 답하지 않았습니다."
    except Exception as exc:  # noqa: BLE001 - 자문 실패가 메인 턴을 깨면 안 된다
        return f"{p} 자문 실패: {str(exc)[:120]}"
