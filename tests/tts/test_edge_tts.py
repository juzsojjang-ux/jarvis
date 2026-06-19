import asyncio
import io

import numpy as np
import soundfile as sf

from jarvis.tts.edge_tts_backend import EdgeTTS


def _wav_bytes(sr=24000, secs=0.1, freq=440):
    t = np.linspace(0, secs, int(sr * secs), endpoint=False)
    tone = (0.2 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, tone, sr, format="WAV", subtype="FLOAT")
    return buf.getvalue()


def test_synth_decodes_to_mono_float32():
    wav = _wav_bytes()

    async def fake_fetch(text, voice):
        return wav

    tts = EdgeTTS(fetch=fake_fetch)
    out = asyncio.run(tts.synth("hello"))
    assert out.dtype == np.float32 and out.ndim == 1 and len(out) > 0
    assert tts.sample_rate == 24000


def test_empty_text_returns_empty():
    tts = EdgeTTS(fetch=None)
    out = asyncio.run(tts.synth("   "))
    assert out.dtype == np.float32 and len(out) == 0


class _FakeSay:
    """주입용 가짜 say 폴백 — 고정 톤 반환."""
    def __init__(self, sample_rate=22050):
        self.sample_rate = sample_rate
        self.calls = []

    async def synth(self, text):
        self.calls.append(text)
        return (0.1 * np.ones(2205, dtype=np.float32))


def test_fetch_failure_falls_back_to_say():
    # edge 실패 시 무음이 아니라 say 폴백으로 소리가 나야 한다(배포 .app 무음 회귀 방지).
    async def boom(text, voice):
        raise RuntimeError("network down")

    say = _FakeSay()
    tts = EdgeTTS(fetch=boom, fallback=say)
    out = asyncio.run(tts.synth("hi"))
    assert len(out) > 0 and out.dtype == np.float32  # 폴백 오디오
    assert say.calls == ["hi"]                       # 폴백이 실제로 호출됨
    assert tts.sample_rate == 22050                  # 폴백의 샘플레이트로 갱신


def test_empty_audio_falls_back_to_say():
    # edge가 '성공'했지만 빈 오디오를 주면 그것도 실패로 보고 폴백.
    async def empty(text, voice):
        return b""

    say = _FakeSay()
    out = asyncio.run(EdgeTTS(fetch=empty, fallback=say).synth("yo"))
    assert len(out) > 0 and say.calls == ["yo"]


def test_fetch_failure_no_fallback_unsupported_os_returns_silence(monkeypatch):
    # macOS·윈도우가 아니고 폴백도 없으면(말 그대로 낼 수단이 없으면) 무음 — 예외는 안 난다.
    monkeypatch.setattr("jarvis.tts.edge_tts_backend.sys.platform", "linux")

    async def boom(text, voice):
        raise RuntimeError("network down")

    out = asyncio.run(EdgeTTS(fetch=boom).synth("hi"))
    assert len(out) == 0


def test_default_os_fallback_picks_say_on_mac(monkeypatch):
    monkeypatch.setattr("jarvis.tts.edge_tts_backend.sys.platform", "darwin")
    from jarvis.tts.system_say import SystemSayTTS
    fb = EdgeTTS._default_os_fallback()
    assert isinstance(fb, SystemSayTTS)


def test_default_os_fallback_picks_sapi_on_windows(monkeypatch):
    monkeypatch.setattr("jarvis.tts.edge_tts_backend.sys.platform", "win32")
    from jarvis.tts.system_sapi import SystemSapiTTS
    fb = EdgeTTS._default_os_fallback()
    assert isinstance(fb, SystemSapiTTS)


def test_default_os_fallback_none_on_unsupported(monkeypatch):
    monkeypatch.setattr("jarvis.tts.edge_tts_backend.sys.platform", "linux")
    assert EdgeTTS._default_os_fallback() is None


def test_warm_prebuilds_os_fallback(monkeypatch):
    # warm()이 no-op이 아니라 부팅에서 OS 폴백을 미리 만들어 둔다 — 기본 Pocket 경로가 받는
    # 예열을 alt(edge) 경로도 스스로 받게 해, 첫 턴에 edge가 실패해도 즉시 들리는 소리로 폴백.
    sentinel = _FakeSay()
    monkeypatch.setattr(EdgeTTS, "_default_os_fallback", staticmethod(lambda: sentinel))
    tts = EdgeTTS(fetch=None, fallback=None)
    assert tts._fallback is None
    tts.warm()
    assert tts._fallback is sentinel  # 예열이 폴백을 선구축함(이전엔 no-op이라 None 유지)


def test_warm_is_safe_when_no_fallback(monkeypatch):
    # 폴백조차 못 만드는 OS여도 warm()은 예외 없이 끝난다(부팅을 막지 않음).
    monkeypatch.setattr(EdgeTTS, "_default_os_fallback", staticmethod(lambda: None))
    tts = EdgeTTS(fetch=None, fallback=None)
    tts.warm()
    assert tts._fallback is None


def test_stereo_downmixed_to_mono():
    sr = 24000
    stereo = (np.random.rand(2400, 2) * 0.1).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, stereo, sr, format="WAV", subtype="FLOAT")
    wav = buf.getvalue()

    async def fake_fetch(text, voice):
        return wav

    out = asyncio.run(EdgeTTS(fetch=fake_fetch).synth("x"))
    assert out.ndim == 1
