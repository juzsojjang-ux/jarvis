"""토큰 사용량 추출/집계 + 한도 초과 판별 테스트."""
from __future__ import annotations

from types import SimpleNamespace

from jarvis.brain.usage import UsageTracker, extract_tokens, is_limit_error


# --- extract_tokens ----------------------------------------------------------
def test_extract_anthropic_style():
    u = SimpleNamespace(input_tokens=120, output_tokens=45)
    assert extract_tokens(u) == (120, 45)


def test_extract_openai_dict():
    assert extract_tokens({"prompt_tokens": 70, "completion_tokens": 30}) == (70, 30)


def test_extract_gemini_usage_metadata():
    u = SimpleNamespace(usage_metadata=SimpleNamespace(
        prompt_token_count=12, candidates_token_count=8))
    assert extract_tokens(u) == (12, 8)


def test_extract_none_is_zero():
    assert extract_tokens(None) == (0, 0)


# --- is_limit_error ----------------------------------------------------------
def test_limit_by_status_429():
    assert is_limit_error(SimpleNamespace(status_code=429)) is True


def test_limit_by_message():
    assert is_limit_error(Exception("Error: rate_limit_error, please retry")) is True
    assert is_limit_error(Exception("You exceeded your current quota")) is True
    assert is_limit_error(Exception("RESOURCE_EXHAUSTED")) is True


def test_not_limit_for_normal_error():
    assert is_limit_error(Exception("connection reset")) is False
    assert is_limit_error(None) is False


# --- UsageTracker ------------------------------------------------------------
def test_tracker_accumulates_session_and_total(tmp_path):
    p = tmp_path / "usage.json"
    t = UsageTracker(p)
    t.record(SimpleNamespace(input_tokens=100, output_tokens=40))
    t.record({"prompt_tokens": 50, "completion_tokens": 10})
    assert t.session == {"input": 150, "output": 50, "turns": 2}
    assert t.total["input"] == 150 and t.total["turns"] == 2


def test_tracker_persists_total_across_instances(tmp_path):
    p = tmp_path / "usage.json"
    UsageTracker(p).record(SimpleNamespace(input_tokens=10, output_tokens=5))
    t2 = UsageTracker(p)  # 새 세션 — 누적은 유지, 세션은 0부터
    assert t2.total["input"] == 10 and t2.total["output"] == 5
    assert t2.session == {"input": 0, "output": 0, "turns": 0}


def test_summary_has_numbers(tmp_path):
    t = UsageTracker(tmp_path / "u.json")
    t.record(SimpleNamespace(input_tokens=1234, output_tokens=56))
    s = t.summary()
    assert "1,234" in s and "사용량"  # noqa: not asserting literal, just numbers present
    assert "토큰" in s
