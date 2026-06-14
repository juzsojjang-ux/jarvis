from jarvis.audio.wake import match_wake

WORDS = ["자비스", "쟈비스", "jarvis"]


def test_wake_with_command():
    ok, cmd = match_wake("자비스 지금 몇 시야?", WORDS)
    assert ok and cmd == "지금 몇 시야?"


def test_bare_wake_word():
    ok, cmd = match_wake("자비스.", WORDS)
    assert ok and cmd == ""


def test_comma_after_wake():
    ok, cmd = match_wake("자비스, 음악 틀어줘", WORDS)
    assert ok and cmd == "음악 틀어줘"


def test_vocative_suffix_stripped():
    ok, cmd = match_wake("자비스야 불 꺼줘", WORDS)
    assert ok and cmd == "불 꺼줘"


def test_command_starting_with_a_sound_not_eaten():
    # '아침'의 '아'를 호격으로 오인해 잘라먹으면 안 된다 (lstrip 함정).
    ok, cmd = match_wake("자비스 아침 날씨 알려줘", WORDS)
    assert ok and cmd == "아침 날씨 알려줘"


def test_english_wake_word_case_insensitive():
    ok, cmd = match_wake("Jarvis open Safari", WORDS)
    assert ok and cmd == "open safari"


def test_non_wake_text_rejected():
    ok, cmd = match_wake("오늘 회의 몇 시지?", WORDS)
    assert not ok and cmd == ""


def test_wake_word_mid_sentence_rejected():
    # 시작이 아니면 호출이 아니다 (대화 중 언급에 반응 금지).
    ok, _ = match_wake("그때 자비스가 말했잖아", WORDS)
    assert not ok


def test_leading_punctuation_ignored():
    ok, cmd = match_wake("... 자비스 볼륨 줄여", WORDS)
    assert ok and cmd == "볼륨 줄여"


# ---- 견고화: 공백 끊김 / 오인식 변형 / '일어나' 트리거 -----------------------
def test_space_split_wake_word():
    # STT가 "자 비스"로 끊어도 인식(공백 무시 매칭).
    ok, cmd = match_wake("자 비스 켜줘", WORDS)
    assert ok and cmd == "켜줘"


def test_space_split_bare_wake():
    ok, cmd = match_wake("자 비스", WORDS)
    assert ok and cmd == ""


def test_default_config_has_wakeup_and_variants():
    from jarvis.core.config import Settings
    words = Settings().wake_words
    ok, cmd = match_wake("일어나 음악 틀어줘", words)
    assert ok and cmd == "음악 틀어줘"
    ok2, cmd2 = match_wake("일어나", words)
    assert ok2 and cmd2 == ""
    ok3, _ = match_wake("재비스 불 꺼줘", words)
    assert ok3
