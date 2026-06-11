import json
from jarvis.brain.history import ConversationHistory


def test_add_and_load_roundtrip(tmp_path):
    p = tmp_path / "h.jsonl"
    h = ConversationHistory(p, max_turns=6)
    h.add("안녕", "Hello, sir.")
    h.add("이름은?", "JARVIS, sir.")
    h2 = ConversationHistory(p, max_turns=6)
    h2.load()
    assert h2.turns == [("안녕", "Hello, sir."), ("이름은?", "JARVIS, sir.")]


def test_trims_to_max_turns(tmp_path):
    p = tmp_path / "h.jsonl"
    h = ConversationHistory(p, max_turns=2)
    for i in range(5):
        h.add(f"q{i}", f"a{i}")
    h2 = ConversationHistory(p, max_turns=2)
    h2.load()
    assert h2.turns == [("q3", "a3"), ("q4", "a4")]


def test_ignores_empty(tmp_path):
    h = ConversationHistory(tmp_path / "h.jsonl")
    h.add("", "x")
    h.add("y", "")
    assert h.turns == []


def test_as_context_empty_is_blank(tmp_path):
    assert ConversationHistory(tmp_path / "h.jsonl").as_context() == ""


def test_as_context_format(tmp_path):
    h = ConversationHistory(tmp_path / "h.jsonl")
    h.add("내 이름은 성재", "Noted, sir.")
    ctx = h.as_context()
    assert "이전 대화 맥락" in ctx
    assert "주인님: 내 이름은 성재" in ctx
    assert "자비스: Noted, sir." in ctx
    assert ctx.rstrip().endswith("[현재 질문]")


def test_load_skips_corrupt_lines(tmp_path):
    p = tmp_path / "h.jsonl"
    p.write_text('{"user":"a","assistant":"b"}\nNOT JSON\n{"user":"c","assistant":"d"}\n')
    h = ConversationHistory(p)
    h.load()
    assert h.turns == [("a", "b"), ("c", "d")]


def test_load_missing_file_is_empty(tmp_path):
    h = ConversationHistory(tmp_path / "nope.jsonl")
    h.load()
    assert h.turns == []


def test_clear(tmp_path):
    p = tmp_path / "h.jsonl"
    h = ConversationHistory(p)
    h.add("a", "b")
    h.clear()
    assert h.turns == []
    h2 = ConversationHistory(p); h2.load()
    assert h2.turns == []


def test_atomic_save_no_temp_left(tmp_path):
    p = tmp_path / "h.jsonl"
    h = ConversationHistory(p)
    h.add("a", "b")
    leftovers = [f.name for f in tmp_path.iterdir() if f.name != "h.jsonl"]
    assert leftovers == []
