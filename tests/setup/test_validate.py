"""tests/setup/test_validate.py — validate.py 단위 테스트.

실제 API 호출은 절대 하지 않는다. 클라이언트는 SimpleNamespace + 비동기 메서드로
주입한다.
"""
from __future__ import annotations

import pytest

from jarvis.setup.validate import validate


# ---------------------------------------------------------------------------
# 헬퍼: 가짜 클라이언트 빌더
# ---------------------------------------------------------------------------

def _make_gemini_client(*, success: bool):
    """aio.models.generate_content 를 흉내내는 객체를 반환한다."""
    from types import SimpleNamespace

    async def _generate_content(model, contents):
        if not success:
            raise RuntimeError("invalid key")

    aio_models = SimpleNamespace(generate_content=_generate_content)
    aio = SimpleNamespace(models=aio_models)
    return SimpleNamespace(aio=aio)


def _make_openai_client(*, success: bool):
    """chat.completions.create를 흉내내는 객체를 반환한다."""
    from types import SimpleNamespace

    async def _create(model, messages, max_tokens):
        if not success:
            raise RuntimeError("invalid key")
        return SimpleNamespace(choices=[])

    completions = SimpleNamespace(create=_create)
    chat = SimpleNamespace(completions=completions)
    return SimpleNamespace(chat=chat)


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_claude_always_ok():
    ok, msg = await validate("claude", "")
    assert ok is True
    assert "Claude" in msg


@pytest.mark.anyio
async def test_claude_with_any_key_ok():
    ok, msg = await validate("claude", "some-key")
    assert ok is True


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_gemini_empty_key_fails():
    ok, msg = await validate("gemini", "   ", gemini_client=_make_gemini_client(success=True))
    assert ok is False
    assert "입력" in msg


@pytest.mark.anyio
async def test_gemini_fake_client_success():
    ok, msg = await validate(
        "gemini", "AIza-test", gemini_client=_make_gemini_client(success=True)
    )
    assert ok is True
    assert "확인" in msg


@pytest.mark.anyio
async def test_gemini_fake_client_failure():
    ok, msg = await validate(
        "gemini", "AIza-bad", gemini_client=_make_gemini_client(success=False)
    )
    assert ok is False
    assert "올바르지" in msg


# ---------------------------------------------------------------------------
# GPT — codex 구독 로그인 확인 (키 불필요)
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_gpt_codex_check_success():
    """codex_check가 True를 반환하면 (True, '확인') 을 반환한다."""
    ok, msg = await validate("gpt", "", codex_check=lambda: True)
    assert ok is True
    assert "확인" in msg


@pytest.mark.anyio
async def test_gpt_codex_check_failure():
    """codex_check가 False를 반환하면 (False, 'codex login') 메시지를 반환한다."""
    ok, msg = await validate("gpt", "", codex_check=lambda: False)
    assert ok is False
    assert "codex login" in msg


# ---------------------------------------------------------------------------
# 알 수 없는 프로바이더
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_unknown_provider():
    ok, msg = await validate("unknown", "key")
    assert ok is False
    assert "알 수 없는" in msg


@pytest.mark.anyio
async def test_empty_provider():
    ok, msg = await validate("", "key")
    assert ok is False
    assert "알 수 없는" in msg
