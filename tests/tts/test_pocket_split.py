from jarvis.tts.pocket_worker import _TOKEN_BUDGET, _token_cost, split_for_pocket


def _cost(piece: str) -> float:
    return sum(_token_cost(w) for w in piece.split())


def test_short_text_is_one_piece():
    assert split_for_pocket("Good evening, sir.") == ["Good evening, sir."]


def test_empty_is_empty():
    assert split_for_pocket("   ") == []


def test_long_clauseless_run_on_is_hard_capped():
    # 40 comma-less words -> split so no piece exceeds the token budget
    text = " ".join(f"word{i}" for i in range(40))
    pieces = split_for_pocket(text)
    assert len(pieces) >= 2
    assert all(_cost(p) <= _TOKEN_BUDGET for p in pieces)
    assert " ".join(pieces).split() == text.split()  # no words lost


def test_prefers_clause_boundary():
    # breaks at the comma once past 60% of the budget, not mid-clause
    text = ("one two three four five six seven eight nine ten eleven twelve, "
            "thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty "
            "twentyone twentytwo twentythree twentyfour twentyfive twentysix.")
    pieces = split_for_pocket(text, budget=25.0)
    assert pieces[0].endswith(",")  # split landed on the clause boundary


def test_korean_is_token_weighted_not_word_counted():
    # 실제 경고 사례: 한국어 확인 안내문(어절 10개 ≈ 55토큰)이 50토큰을 넘겨
    # "generation may skip words" 경고가 났다 — 단어 수가 아니라 토큰 가중으로
    # 쪼개져 모든 조각이 예산 안에 들어와야 한다.
    text = "송신 확인. 메시지를 보낼까요? 진행하려면 '네', 취소하려면 '아니오'라고 말씀해 주세요."
    pieces = split_for_pocket(text)
    assert len(pieces) >= 2
    assert all(_cost(p) <= _TOKEN_BUDGET for p in pieces)
    assert " ".join(pieces).split() == text.split()  # 단어 손실 없음


def test_hangul_costs_about_three_tokens_each():
    # 측정 근거 고정: 한글 음절 ≈ 3토큰 가중치 (회귀 방지)
    assert _token_cost("가나다") >= 9.0


def test_tiny_trailing_piece_merged():
    # 초단편 꼬리 조각(예: "네.")은 이웃과 병합 — 짧은 입력 웅얼거림(뭉개짐) 방지.
    pieces = split_for_pocket("진행하려면 네라고 말씀해 주세요. 알겠습니다 주인님. 네.", budget=20.0)
    assert all(sum(_token_cost(w) for w in p.split()) >= 6.0 for p in pieces[1:]) or len(pieces) == 1
    joined = " ".join(pieces).split()
    assert joined == "진행하려면 네라고 말씀해 주세요. 알겠습니다 주인님. 네.".split()
