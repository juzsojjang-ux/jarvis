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
    # 중복제거 키 — 같은 종류라도 인스턴스가 다르면(타이머 라벨별·작업 id별) 별개로 큐잉되게
    # 한다. None이면 kind로 폴백(기존 동작). kind는 쿨다운 분류용으로 그대로 유지.
    dedup_key: str | None = None

    @property
    def dkey(self) -> str:
        return self.dedup_key or self.kind

    def expired(self, now: float) -> bool:
        return now >= self.expires_at
