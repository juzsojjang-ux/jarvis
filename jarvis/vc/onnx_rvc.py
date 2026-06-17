"""torch-free ONNX RVC 음색 변환 — onnxruntime(contentvec + 신디사이저) + pyworld(피치).
배포판에 번들 가능(torch 불필요, 맥·윈도우 공통). 모델: jarvis.onnx(신디사이저) +
vec-768-layer-12.onnx(contentvec). RVCConversion과 같은 VoiceConversion 계약."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

_SR = 40000
_HOP = 512


class _Dio:
    """pyworld DIO 피치 추출기(rvc-python DioF0Predictor 포팅, torch 무관)."""
    def __init__(self, hop=_HOP, sr=_SR, f0_min=50, f0_max=1100):
        self.hop, self.sr, self.f0_min, self.f0_max = hop, sr, f0_min, f0_max

    def _interp(self, f0):
        d = np.reshape(f0, (f0.size, 1))
        vuv = np.zeros((d.size, 1), np.float32); vuv[d > 0] = 1
        ip = d; n = d.size; last = 0.0
        for i in range(n):
            if d[i] <= 0:
                j = i + 1
                for j in range(i + 1, n):
                    if d[j] > 0: break
                if j < n - 1:
                    if last > 0:
                        step = (d[j] - d[i - 1]) / float(j - i)
                        for k in range(i, j): ip[k] = d[i - 1] + step * (k - i + 1)
                    else:
                        for k in range(i, j): ip[k] = d[j]
                else:
                    for k in range(i, n): ip[k] = last
            else:
                ip[i] = d[i]; last = d[i]
        return ip[:, 0], vuv[:, 0]

    def _resize(self, x, tl):
        src = np.array(x); src[src < 0.001] = np.nan
        t = np.interp(np.arange(0, len(src) * tl, len(src)) / tl,
                      np.arange(0, len(src)), src)
        return np.nan_to_num(t)

    def compute_f0(self, wav, p_len):
        import pyworld
        f0, t = pyworld.dio(wav.astype(np.double), fs=self.sr, f0_floor=self.f0_min,
                            f0_ceil=self.f0_max, frame_period=1000 * self.hop / self.sr)
        f0 = pyworld.stonemask(wav.astype(np.double), f0, t, self.sr)
        return self._interp(self._resize(f0, p_len))[0]


class OnnxRVCConversion:
    def __init__(self, model_path: str, contentvec_path: str, sample_rate: int = _SR,
                 f0_up: int = 0, session_factory=None):
        self.model_path = str(model_path)
        self.contentvec_path = str(contentvec_path)
        # 출력은 항상 _SR(모델 고정 출력률)이다. 설정값을 그대로 저장하면 실제 출력률과
        # 달라 호출부(재생 리샘플)가 잘못된 비율을 쓴다(audit medium). 실제 출력률로 고정.
        self.sample_rate = _SR
        self.f0_up = f0_up
        self._session_factory = session_factory  # 주입(테스트). None이면 실제 onnxruntime
        self._vec = None
        self._syn = None
        self._dio = _Dio()

    def _sessions(self):
        if self._vec is None or self._syn is None:
            if self._session_factory is not None:
                self._vec = self._session_factory(self.contentvec_path)
                self._syn = self._session_factory(self.model_path)
            else:
                import onnxruntime
                self._vec = onnxruntime.InferenceSession(
                    self.contentvec_path, providers=["CPUExecutionProvider"])
                self._syn = onnxruntime.InferenceSession(
                    self.model_path, providers=["CPUExecutionProvider"])
        return self._vec, self._syn

    def warm(self) -> None:
        try:
            self.convert(np.zeros(int(0.5 * _SR), dtype=np.float32), _SR)
        except Exception:  # noqa: BLE001 - 예열 실패 무해
            pass

    def convert(self, pcm: np.ndarray, in_rate: int) -> np.ndarray:
        import librosa
        vec, syn = self._sessions()
        wav = np.asarray(pcm, dtype=np.float32).reshape(-1)
        if in_rate != _SR:
            wav = librosa.resample(wav, orig_sr=in_rate, target_sr=_SR)
        org = len(wav)
        if org < _HOP:  # 너무 짧으면 그대로 반환(빈/무음)
            return wav.astype(np.float32)
        wav16 = librosa.resample(wav, orig_sr=_SR, target_sr=16000)
        feats = np.expand_dims(np.expand_dims(wav16, 0), 0)
        hub = vec.run(None, {vec.get_inputs()[0].name: feats})[0].transpose(0, 2, 1)
        hub = np.repeat(hub, 2, axis=2).transpose(0, 2, 1).astype(np.float32)
        hl = hub.shape[1]
        f0_min, f0_max = 50, 1100
        fmel_min = 1127 * np.log(1 + f0_min / 700)
        fmel_max = 1127 * np.log(1 + f0_max / 700)
        pf = self._dio.compute_f0(wav, hl) * 2 ** (self.f0_up / 12)
        p = pf.copy(); fmel = 1127 * np.log(1 + p / 700)
        fmel[fmel > 0] = (fmel[fmel > 0] - fmel_min) * 254 / (fmel_max - fmel_min) + 1
        fmel[fmel <= 1] = 1; fmel[fmel > 255] = 255
        p = np.rint(fmel).astype(np.int64)
        pf = pf.reshape(1, len(pf)).astype(np.float32)
        p = p.reshape(1, len(p))
        ds = np.array([0]).astype(np.int64)
        rnd = np.random.randn(1, 192, hl).astype(np.float32)
        hla = np.array([hl]).astype(np.int64)
        ins = syn.get_inputs()
        inp = {ins[0].name: hub, ins[1].name: hla, ins[2].name: p,
               ins[3].name: pf, ins[4].name: ds, ins[5].name: rnd}
        out = (syn.run(None, inp)[0] * 32767).astype(np.int16).squeeze()
        out = np.pad(out, (0, 2 * _HOP), "constant")[:org]
        return (out.astype(np.float32) / 32768.0)
