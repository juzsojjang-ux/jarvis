"""GPTBrain subscription 모드 테스트 — 가짜 Responses API 클라이언트, 실제 API 미호출."""
from __future__ import annotations

import asyncio
import json
import types as pyt

import pytest

from jarvis.brain.openai_brain import GPTBrain
from jarvis.core.config import Settings


# ---------------------------------------------------------------------------
# 가짜 Responses API 클라이언트
# ---------------------------------------------------------------------------

def _fc(name: str, args: dict, call_id: str = "c1") -> pyt.SimpleNamespace:
    """SimpleNamespace function_call 항목."""
    return pyt.SimpleNamespace(
        type="function_call",
        name=name,
        arguments=json.dumps(args),
        call_id=call_id,
    )


def _resp(
    output_items: list | None = None,
    output_text: str | None = None,
) -> pyt.SimpleNamespace:
    """Responses API 응답 모방."""
    return pyt.SimpleNamespace(
        output=output_items or [],
        output_text=output_text,
    )


class _FakeResponses:
    def __init__(self, scripted: list):
        self.scripted = list(scripted)
        self.calls: list[dict] = []

    async def create(self, **kw) -> pyt.SimpleNamespace:
        self.calls.append(kw)
        return self.scripted.pop(0)


class _FakeSubClient:
    """subscription 모드 가짜 클라이언트 (responses.create만 있음)."""

    def __init__(self, scripted: list):
        self.responses = _FakeResponses(scripted)

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _sub_settings() -> Settings:
    s = Settings()
    s.gpt_auth = "subscription"  # type: ignore[assignment]
    return s


def _brain(scripted: list, **kw) -> GPTBrain:
    return GPTBrain(
        _sub_settings(),
        kw.pop("memory", None),
        "p" * 4096,
        client=_FakeSubClient(scripted),
        **kw,
    )


async def _collect(agen) -> list[str]:
    return [x async for x in agen]


# ---------------------------------------------------------------------------
# 기본 텍스트 응답 — [KO] 분리
# ---------------------------------------------------------------------------

def test_subscription_plain_answer_splits_ko():
    b = _brain([_resp(output_text="Two, sir.[KO] 두 시.")])
    out = "".join(asyncio.run(_collect(b.respond("몇시"))))
    assert out.strip() == "Two, sir."
    assert b.last_subtitle == "두 시."


# ---------------------------------------------------------------------------
# output_items 방식 텍스트 (output_text가 None일 때)
# ---------------------------------------------------------------------------

def test_subscription_plain_answer_via_output_items():
    part = pyt.SimpleNamespace(type="output_text", text="Yes, sir.")
    msg_item = pyt.SimpleNamespace(type="message", content=[part])
    b = _brain([_resp(output_items=[msg_item], output_text=None)])
    out = "".join(asyncio.run(_collect(b.respond("ok"))))
    assert "Yes, sir." in out


# ---------------------------------------------------------------------------
# 도구 호출 → 결과 피드백 → 최종 답변
# ---------------------------------------------------------------------------

def test_subscription_tool_then_answer():
    scripted = [
        _resp(output_items=[_fc("get_time", {})]),
        _resp(output_text="Time noted, sir.[KO] 시간이요."),
    ]
    b = _brain(scripted)
    out = "".join(asyncio.run(_collect(b.respond("몇시야"))))
    assert "time" in out.lower() or "noted" in out.lower()
    assert b.last_subtitle == "시간이요."

    # 두 번째 호출 input에 function_call + function_call_output 포함 확인
    second_input = b._client_instance.responses.calls[1]["input"]
    types_in_input = [item.get("type") for item in second_input if isinstance(item, dict)]
    assert "function_call" in types_in_input
    assert "function_call_output" in types_in_input


# ---------------------------------------------------------------------------
# send_message — confirm 없음 → 거부
# ---------------------------------------------------------------------------

def test_subscription_send_denied_without_confirm():
    scripted = [
        _resp(output_items=[_fc("send_message", {"recipient": "민지", "text": "hi"})]),
        _resp(output_text="Couldn't send.[KO] 못 보냈습니다."),
    ]
    b = _brain(scripted)
    asyncio.run(_collect(b.respond("보내줘")))

    second_input = b._client_instance.responses.calls[1]["input"]
    outputs = [
        item["output"]
        for item in second_input
        if isinstance(item, dict) and item.get("type") == "function_call_output"
    ]
    assert outputs
    assert "취소" in outputs[0] or "확인" in outputs[0]


# ---------------------------------------------------------------------------
# remote_mode — 읽기 전용 외 차단
# ---------------------------------------------------------------------------

def test_subscription_remote_blocks_action():
    scripted = [
        _resp(output_items=[_fc("open_app", {"app": "Notes"})]),
        _resp(output_text="Remote.[KO] 원격."),
    ]
    b = _brain(scripted)
    b.remote_mode = True
    asyncio.run(_collect(b.respond("메모 열어")))

    second_input = b._client_instance.responses.calls[1]["input"]
    outputs = [
        item["output"]
        for item in second_input
        if isinstance(item, dict) and item.get("type") == "function_call_output"
    ]
    assert outputs
    assert "원격" in outputs[0]


# ---------------------------------------------------------------------------
# remote_mode — 읽기 전용 도구는 허용
# ---------------------------------------------------------------------------

def test_subscription_remote_allows_readonly():
    scripted = [
        _resp(output_items=[_fc("get_time", {})]),
        _resp(output_text="Time.[KO] 시간."),
    ]
    b = _brain(scripted)
    b.remote_mode = True
    asyncio.run(_collect(b.respond("몇시야")))

    second_input = b._client_instance.responses.calls[1]["input"]
    # get_time은 허용 → function_call_output이 있어야 함
    outputs = [
        item
        for item in second_input
        if isinstance(item, dict) and item.get("type") == "function_call_output"
    ]
    assert outputs


# ---------------------------------------------------------------------------
# translate — subscription 모드
# ---------------------------------------------------------------------------

def test_subscription_translate():
    b = _brain([_resp(output_text="Hello")])
    result = asyncio.run(b.translate("안녕", "English"))
    assert result == "Hello"

    # responses.create 호출되었고 instructions에 Translate 포함 확인
    call = b._client_instance.responses.calls[0]
    assert "Translate" in call.get("instructions", "")


# ---------------------------------------------------------------------------
# 빈 output_text → 빈 출력, 오류 없음
# ---------------------------------------------------------------------------

def test_subscription_empty_response_no_crash():
    b = _brain([_resp(output_text="")])
    out = "".join(asyncio.run(_collect(b.respond("아무거나"))))
    assert out == ""


# ---------------------------------------------------------------------------
# responses.create 예외 → 빈 출력, 크래시 없음
# ---------------------------------------------------------------------------

def test_subscription_exception_no_crash():
    class _ErrorResponses:
        async def create(self, **kw):
            raise RuntimeError("API error")

    class _ErrorClient:
        def __init__(self):
            self.responses = _ErrorResponses()

        async def close(self):
            pass

    b = GPTBrain(_sub_settings(), None, "p" * 4096, client=_ErrorClient())
    out = "".join(asyncio.run(_collect(b.respond("오류"))))
    assert out == ""


# ---------------------------------------------------------------------------
# history — 대화 후 저장되는지 확인
# ---------------------------------------------------------------------------

def test_subscription_history_saved(monkeypatch, tmp_path):
    monkeypatch.setattr("jarvis.brain.history.DEFAULT_HISTORY_PATH", tmp_path / "h.jsonl")
    b = _brain([_resp(output_text="Yes.[KO] 네.")])
    asyncio.run(_collect(b.respond("테스트")))
    assert len(b._history.turns) == 1
    assert b._history.turns[0] == ("테스트", "Yes.")


# ---------------------------------------------------------------------------
# 도구 목록 형식 확인 — Responses API는 평면 function (type+name+description+parameters)
# ---------------------------------------------------------------------------

def test_subscription_tools_payload_format():
    b = _brain([])
    tools = b._responses_tools()
    assert tools
    t = tools[0]
    assert t["type"] == "function"
    assert "name" in t
    assert "description" in t
    assert "parameters" in t
    # Chat Completions와 달리 "function" 중첩 없음
    assert "function" not in t


# ---------------------------------------------------------------------------
# _ensure_client — 이미 주입된 클라이언트는 get_access 미호출
# ---------------------------------------------------------------------------

def test_ensure_client_uses_injected_client():
    """생성자에 client 주입 시 _ensure_client가 곧바로 반환."""
    called = []

    async def _fake_get_access(*a, **kw):  # pragma: no cover
        called.append(True)
        return "tok", "acct"

    import jarvis.brain.codex_auth as _ca
    original = _ca.get_access

    b = _brain([])  # client already injected via _FakeSubClient

    async def _run():
        return await b._ensure_client()

    result = asyncio.run(_run())
    assert result is b._client_instance
    assert not called  # get_access never called
