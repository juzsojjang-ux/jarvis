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


def test_remember_skips_duplicate(tmp_path):
    from jarvis.brain.memory import MemoryStore
    m = MemoryStore(tmp_path / "mem.md")
    m.load()
    m.remember("주인님은 매운 음식을 못 먹는다")
    m.remember("주인님은 매운 음식을 못 먹는다")
    m.remember("주인님은  매운 음식을 못먹는다!!")
    assert m.text().count("매운 음식") == 1


def test_remember_substring_duplicate(tmp_path):
    from jarvis.brain.memory import MemoryStore
    m = MemoryStore(tmp_path / "mem.md")
    m.load()
    m.remember("커피는 아메리카노")
    m.remember("커피는 아메리카노만 마신다")
    assert m.text().count("아메리카노") == 1


def test_remember_distinct_kept(tmp_path):
    from jarvis.brain.memory import MemoryStore
    m = MemoryStore(tmp_path / "mem.md")
    m.load()
    m.remember("이름은 이성재")
    m.remember("생일은 3월")
    assert "이성재" in m.text() and "3월" in m.text()
