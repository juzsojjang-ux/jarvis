from jarvis.proactive.timers import TimerBoard


def _board():
    t = {"v": 0.0}
    return TimerBoard(clock=lambda: t["v"]), t


def test_add_and_pop_due_in_order():
    board, t = _board()
    board.add(10, "라면")
    board.add(5, "달걀")
    assert board.pop_due() == []
    t["v"] = 6.0
    assert board.pop_due() == ["달걀"]
    t["v"] = 11.0
    assert board.pop_due() == ["라면"]
    assert board.pop_due() == []


def test_default_label_and_min_duration():
    board, t = _board()
    _tid, label = board.add(0, "")
    assert label == "타이머"
    t["v"] = 1.0
    assert board.pop_due() == ["타이머"]


def test_listing_remaining_seconds():
    board, t = _board()
    board.add(90, "회의")
    t["v"] = 30.0
    assert board.listing() == [("회의", 60)]


def test_cancel_by_label_substring():
    board, _ = _board()
    board.add(60, "라면 타이머")
    assert "취소" in board.cancel("라면")
    assert board.listing() == []


def test_cancel_without_label():
    board, _ = _board()
    assert "없습니다" in board.cancel("")
    board.add(60, "하나")
    assert "'하나'" in board.cancel("")
    board.add(60, "a")
    board.add(60, "b")
    out = board.cancel("")
    assert "여러 개" in out and "a" in out
    assert "찾지 못했습니다" in board.cancel("없는라벨")
