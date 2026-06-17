from types import SimpleNamespace

from jarvis.core.interpret import detect_lang, interpret_speak_korean


def test_detect_lang_korean():
    assert detect_lang("안녕하세요") == "ko"
    assert detect_lang("자비스 오늘 날씨") == "ko"


def test_detect_lang_english():
    assert detect_lang("hello there") == "en"
    assert detect_lang("what time is it") == "en"


def test_detect_lang_mixed_is_korean():
    assert detect_lang("ok 그래") == "ko"


def test_detect_lang_empty_is_english():
    assert detect_lang("") == "en"
    assert detect_lang("12345 !!!") == "en"


def test_speak_korean_invokes_say(monkeypatch):
    # 맥 경로(say) 검증 — 윈도우는 PowerShell 분기라 플랫폼을 darwin으로 고정한다.
    monkeypatch.setattr("jarvis.core.interpret.sys.platform", "darwin")
    calls = []

    def runner(cmd, capture_output=True, text=True, timeout=None):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    interpret_speak_korean("안녕하세요", voice="Yuna", runner=runner)
    assert calls == [["say", "-v", "Yuna", "안녕하세요"]]


def test_speak_korean_swallows_failure():
    def boom(cmd, capture_output=True, text=True, timeout=None):
        raise RuntimeError("say missing")

    interpret_speak_korean("안녕", runner=boom)
