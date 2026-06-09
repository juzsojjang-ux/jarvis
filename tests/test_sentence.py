from jarvis.brain.sentence import SentenceChunker


def test_flush_on_period_and_question():
    c = SentenceChunker()
    assert c.feed("안녕하") == []
    assert c.feed("세요. ") == ["안녕하세요."]
    assert c.feed("무엇을 도와드릴까요? ") == ["무엇을 도와드릴까요?"]
    assert c.flush() is None


def test_korean_ender_with_whitespace():
    c = SentenceChunker()
    # "네"(ender) followed by whitespace -> boundary
    assert c.feed("네 반갑습니다") == ["네"]
    assert c.flush() == "반갑습니다"


def test_max_char_fallback():
    c = SentenceChunker(max_chars=10)
    out = c.feed("가" * 10)
    assert out == ["가" * 10]
    assert c.flush() is None


def test_partial_then_flush():
    c = SentenceChunker()
    assert c.feed("반갑습니다") == []  # ender "다" at end, no trailing space -> held
    assert c.flush() == "반갑습니다"
