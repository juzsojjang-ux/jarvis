from jarvis.tts.pocket_worker import split_for_pocket


def test_short_text_is_one_piece():
    assert split_for_pocket("Good evening, sir.") == ["Good evening, sir."]


def test_empty_is_empty():
    assert split_for_pocket("   ") == []


def test_long_clauseless_run_on_is_hard_capped():
    # 40 comma-less words -> must be split so no piece exceeds the word budget + slack
    text = " ".join(f"word{i}" for i in range(40))
    pieces = split_for_pocket(text, max_words=24)
    assert len(pieces) >= 2
    assert all(len(p.split()) <= 24 + 8 for p in pieces)
    assert " ".join(pieces).split() == text.split()  # no words lost


def test_prefers_clause_boundary():
    # breaks after the comma once past the limit, not mid-clause
    text = ("one two three four five six seven eight nine ten eleven twelve, "
            "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty "
            "twentyone twentytwo twentythree twentyfour twentyfive twentysix.")
    pieces = split_for_pocket(text, max_words=12)
    assert pieces[0].endswith(",")  # split landed on the clause boundary
