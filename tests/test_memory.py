from jarvis.brain.memory import MemoryStore


def test_remember_persists_across_restart(tmp_path):
    path = tmp_path / "sub" / "memory.md"
    m1 = MemoryStore(path)
    m1.load()
    assert m1.text() == ""
    m1.remember("사용자 이름은 이성재")
    m1.remember("  ")  # blank ignored
    m1.remember("한국어로 답한다")

    # Fresh instance = process restart
    m2 = MemoryStore(path)
    m2.load()
    txt = m2.text()
    assert "사용자 이름은 이성재" in txt
    assert "한국어로 답한다" in txt
    assert txt.count("\n") == 2  # blank not written


def test_text_empty_when_file_absent(tmp_path):
    m = MemoryStore(tmp_path / "none.md")
    m.load()
    assert m.text() == ""
