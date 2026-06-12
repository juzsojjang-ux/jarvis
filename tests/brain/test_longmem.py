"""장기 기억 — append-only 아카이브, 바이그램 검색, 주입 블록."""
from __future__ import annotations

from datetime import datetime

from jarvis.brain.longmem import LongMemory


def _lm(tmp_path):
    return LongMemory(tmp_path / "lm.jsonl",
                      now_fn=lambda: datetime(2026, 6, 12, 21, 0))


def test_append_and_search(tmp_path):
    lm = _lm(tmp_path)
    lm.append("프리미어 프로 자막 넣어줘", "자막을 넣었습니다")
    lm.append("내일 비 와?", "맑겠습니다")
    hits = lm.search("프리미어 자막 어떻게 했었지")
    assert hits and "프리미어" in hits[0]["user"]


def test_search_no_match_returns_empty(tmp_path):
    lm = _lm(tmp_path)
    lm.append("배고프다", "식사를 권합니다")
    assert lm.search("양자역학 슈뢰딩거 방정식") == []


def test_context_block_format(tmp_path):
    lm = _lm(tmp_path)
    lm.append("리코 영상 줌펀치 120으로", "적용했습니다")
    blk = lm.context_block("줌펀치 몇이었지")
    assert "[장기 기억" in blk and "줌펀치" in blk and blk.endswith("\n")


def test_context_block_empty_when_no_hits(tmp_path):
    lm = _lm(tmp_path)
    assert lm.context_block("아무거나") == ""


def test_blank_user_not_archived(tmp_path):
    lm = _lm(tmp_path)
    lm.append("  ", "답")
    assert lm.search("답") == []


def test_corrupt_lines_skipped(tmp_path):
    f = tmp_path / "lm.jsonl"
    f.write_text('{"ts":"2026-06-12 20:00","user":"커피 주문","assistant":"했습니다"}\n깨진줄{{{\n',
                 encoding="utf-8")
    lm = LongMemory(f)
    assert lm.search("커피")  # 깨진 줄 무시하고 검색됨


def test_history_add_feeds_longmem(tmp_path, monkeypatch):
    """ConversationHistory.add 한 곳만 거치면 모든 두뇌가 장기 기억을 얻는다."""
    monkeypatch.setattr("jarvis.brain.longmem.DEFAULT_LONGMEM_PATH", tmp_path / "lm.jsonl")
    from jarvis.brain.history import ConversationHistory
    h = ConversationHistory(tmp_path / "h.jsonl")
    h.add("오늘 운동 기록해줘", "기록했습니다")
    lm = LongMemory(tmp_path / "lm.jsonl")
    assert lm.search("운동 기록")
