"""Brain 프로토콜 — 모든 두뇌 어댑터(Claude/Gemini/GPT)가 만족해야 할 계약.

runtime_checkable로 정의해 ``isinstance(brain_instance, Brain)`` 체크가 가능하다.
어댑터는 반드시 상속할 필요 없이 구조적으로(structural) 계약을 만족하면 된다.

[KO] 규약
  respond()는 발화할 영어 청크를 yield하고, 마지막으로 반드시
  ``[KO] <한국어 번역>`` 형태의 마커를 포함한 청크를 yield해야 한다.
  이 마커는 화면 자막용으로만 쓰이며, 음성 파이프라인은 마커 앞의 영어만 읽는다.
  split_ko() 헬퍼로 영어/한국어 파트를 분리한다.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

BRAIN_PROVIDERS = ("claude", "gemini", "gpt")

KO_MARK = "[KO]"


def now_stamp(now=None) -> str:
    """매 턴 사용자 입력 앞에 붙이는 실시간 타임스탬프.

    LLM은 오늘 날짜를 모른다 — 도구(get_time)를 안 부르고 학습 시점 기억으로
    추측하면 틀린 날짜를 말한다(실사용 보고 버그). 정답을 항상 입력에 실어보내
    날짜/시간 질문이 도구 없이도 정확하게 한다."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = now or datetime.now(ZoneInfo("Asia/Seoul"))
    days = "월화수목금토일"
    return (f"[지금: {now.year}-{now.month:02d}-{now.day:02d}({days[now.weekday()]}) "
            f"{now.hour:02d}:{now.minute:02d} KST]")


def split_ko(full_text: str) -> tuple[str, str]:
    """[KO] 마커로 영어 파트와 한국어 파트를 분리한다.

    마커가 없으면 (full_text, "") 반환.
    마커가 여러 개면 첫 번째 마커만 분리점으로 쓴다.

    Examples::

        >>> split_ko("Hello, sir.[KO] 안녕하세요, 주인님.")
        ('Hello, sir.', '안녕하세요, 주인님.')
        >>> split_ko("Just English, sir.")
        ('Just English, sir.', '')
    """
    before, sep, after = full_text.partition(KO_MARK)
    if not sep:
        return before.strip(), ""
    return before.strip(), after.strip()


@runtime_checkable
class Brain(Protocol):
    """두뇌 프로바이더가 구현해야 할 인터페이스.

    오케스트레이터·remote·interpret 코드가 이 인터페이스에만 의존한다.
    Claude(subscription/api), Gemini, GPT 어댑터가 구조적으로 conform한다.
    """

    last_subtitle: str
    remote_mode: bool

    async def respond(self, user_text: str) -> AsyncIterator[str]:
        """발화할 영어 텍스트를 청크 단위로 yield한다.

        최후 청크에 ``[KO] <한국어>`` 마커를 포함하는 것이 계약이다.
        last_subtitle 속성을 한국어 자막으로 갱신해야 한다.
        """
        ...  # pragma: no cover

    async def warm(self) -> None:
        """부팅 예열 — best-effort, 실패해도 무시."""
        ...  # pragma: no cover

    async def translate(self, text: str, target_lang: str) -> str:
        """target_lang으로 text를 번역해 반환한다(통역 모드용)."""
        ...  # pragma: no cover

    async def warm_interpret(self) -> None:
        """통역 토글 on에서 백그라운드 예열 — optional(hasattr 가드됨)."""
        ...  # pragma: no cover

    async def close(self) -> None:
        """종료 시 리소스 정리."""
        ...  # pragma: no cover
