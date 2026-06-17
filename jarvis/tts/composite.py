"""FallbackTTS — primary 우선, 실패하면 fallback. 배포 .app에서 Pocket 워커가 죽어도
(가중치 로드 실패·torch 문제 등) edge로 최소한 소리는 나게 한다(무음 금지).

primary가 한 번 예외로 죽으면 그 세션 동안은 바로 fallback을 쓴다 — 죽은 워커를 매 턴
재spawn→즉사 시키며 지연을 쌓지 않기 위해. (audit: factory 주석이 'edge 폴백'을
약속했지만 실제 폴백 코드가 없어 런타임 Pocket 실패 시 영구 무음이던 것을 실배선.)"""
from __future__ import annotations

import asyncio
import logging

import numpy as np

_log = logging.getLogger(__name__)


class FallbackTTS:
    def __init__(self, primary, fallback):
        self._primary = primary
        self._fallback = fallback
        self.sample_rate = getattr(primary, "sample_rate", 24000)
        self._primary_dead = False
        # synth 직렬화 — sample_rate를 공유 속성에 쓰므로 동시 호출 시 write/read 경합 방지
        # (audit r2 low). 정상 사용은 턴당 순차 호출이라 사실상 무경합이나 방어적으로.
        self._lock = asyncio.Lock()

    def warm(self) -> None:
        for t in (self._primary, self._fallback):
            try:
                t.warm()
            except Exception:  # noqa: BLE001 - 예열 실패는 무해
                pass

    async def synth(self, text: str) -> np.ndarray:
        async with self._lock:
            if not self._primary_dead:
                try:
                    out = await self._primary.synth(text)
                    if out is not None and getattr(out, "size", 0) > 0:
                        self.sample_rate = getattr(self._primary, "sample_rate", self.sample_rate)
                        return out
                    # primary가 빈 오디오: 텍스트 자체가 비었으면 정상(폴백도 빈 것) → 그대로.
                    if not (text or "").strip():
                        return out if out is not None else np.zeros(0, dtype=np.float32)
                    _log.warning("기본 TTS가 비-빈 텍스트에 빈 오디오 반환 — 폴백 사용")
                except Exception as exc:  # noqa: BLE001 - 워커 사망 등 → 폴백 전환(무음 금지)
                    _log.warning("기본 TTS 실패(%s: %s) — 이후 폴백으로 전환",
                                 type(exc).__name__, exc)
                    self._primary_dead = True
            out = await self._fallback.synth(text)
            self.sample_rate = getattr(self._fallback, "sample_rate", self.sample_rate)
            return out

    def close(self) -> None:
        for t in (self._primary, self._fallback):
            c = getattr(t, "close", None)
            if callable(c):
                try:
                    c()
                except Exception:  # noqa: BLE001
                    pass
