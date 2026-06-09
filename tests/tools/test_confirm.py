from jarvis.tools.confirm import VoiceConfirm, parse_korean_confirmation


def test_parse_yes_variants():
    for s in ["네", "예", "응", "네 진행해주세요", "응 그래 좋아"]:
        assert parse_korean_confirmation(s) is True


def test_parse_no_variants():
    for s in ["아니", "아니오", "아니요", "취소해줘", "그만"]:
        assert parse_korean_confirmation(s) is False


def test_parse_unclear_returns_none():
    assert parse_korean_confirmation("") is None
    assert parse_korean_confirmation("   ") is None
    assert parse_korean_confirmation("음 글쎄요") is None


def test_negative_takes_priority_for_safety():
    # Ambiguous "아니 네" must NOT confirm an irreversible action.
    assert parse_korean_confirmation("아니 네") is False


def test_voiceconfirm_exposes_async_confirm():
    import inspect

    vc = VoiceConfirm(
        tts=None, vc=None, playback=None, capture=None, stt=None, settings=None
    )
    assert inspect.iscoroutinefunction(vc.confirm)
