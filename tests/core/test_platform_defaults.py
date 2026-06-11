import types
from jarvis.core.platform_defaults import apply_platform_defaults


def _s(**kw):
    base = dict(tts_backend="pocket", vc_backend="null", rvc_f0_up=-12, stt_backend="mlx")
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_windows_switches_voice_chain():
    s = _s()
    apply_platform_defaults(s, system="win32")
    assert s.tts_backend == "edge" and s.vc_backend == "rvc"
    assert s.rvc_f0_up == 0 and s.stt_backend == "faster"


def test_mac_untouched():
    s = _s()
    apply_platform_defaults(s, system="darwin")
    assert s.tts_backend == "pocket" and s.vc_backend == "null"
    assert s.rvc_f0_up == -12 and s.stt_backend == "mlx"


def test_linux_untouched():
    s = _s()
    apply_platform_defaults(s, system="linux")
    assert s.tts_backend == "pocket"


def test_explicit_user_value_not_overridden_on_windows():
    # 사용자가 명시적으로 say를 골랐으면(맥 기본 pocket과 다름) 윈도우라도 안 덮음
    s = _s(tts_backend="say")
    apply_platform_defaults(s, system="win32")
    assert s.tts_backend == "say"
