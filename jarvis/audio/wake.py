from __future__ import annotations

_PUNCT = " \t,.!?~…·-—\"'""''"


def match_wake(text: str, wake_words: list[str]) -> tuple[bool, str]:
    """변환 텍스트가 웨이크워드로 '시작'하는지 판정하고 명령부를 돌려준다.
    (True, 명령) / (False, ""). 문장 중간 언급은 호출이 아니다."""
    t = text.strip().lower().lstrip(_PUNCT)
    for w in wake_words:
        wl = w.lower()
        if not t.startswith(wl):
            continue
        rest = t[len(wl):]
        # 직접 붙은 호격("자비스야")만 제거 — 뒤 단어의 첫 글자('아침')는 보존.
        if rest[:1] in ("야", "아") and (len(rest) <= 1 or rest[1] in _PUNCT):
            rest = rest[1:]
        return True, rest.lstrip(_PUNCT).strip()
    return False, ""
