from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Announcement:
    """능동 알림 한 건. priority는 낮을수록 급함(0=배터리 위험). 시각은 엔진이
    쓰는 단조 시계(clock) 기준 — 벽시계와 섞지 말 것."""

    kind: str
    prompt: str       # 두뇌에 줄 한국어 이벤트 설명
    priority: int
    created_at: float
    expires_at: float

    def expired(self, now: float) -> bool:
        return now >= self.expires_at
