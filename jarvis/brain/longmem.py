"""장기 기억 — 모든 대화 턴을 날짜와 함께 영구 보관하고, 관련된 것을 찾아낸다.

ConversationHistory(최근 N턴 롤링)와 달리 여기는 **지워지지 않는 아카이브**다.
"지난주에 내가 뭐 부탁했지?" 같은 회상과, 매 턴 관련 기억 자동 주입에 쓴다.

검색은 외부 의존성 없는 문자 바이그램 겹침(한국어는 띄어쓰기가 불규칙해 단어
단위보다 강건) + 최근 가중. 모든 I/O는 최선 노력 — 실패해도 대화는 계속된다.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

DEFAULT_LONGMEM_PATH = Path.home() / ".jarvis" / "longmem.jsonl"

_MAX_ENTRIES_SCANNED = 2000   # 검색 시 최근 N건만 본다(파일은 무한 보관)
_SNIPPET = 160                # 주입 발췌 길이


def _bigrams(text: str) -> set[str]:
    t = "".join(text.split()).lower()
    return {t[i:i + 2] for i in range(len(t) - 1)} if len(t) > 1 else {t} if t else set()


class LongMemory:
    """JSONL append-only 아카이브 + 바이그램 검색."""

    def __init__(self, path: Path | None = None, now_fn=datetime.now):
        self._path = Path(path) if path is not None else DEFAULT_LONGMEM_PATH
        self._now = now_fn

    def append(self, user: str, assistant: str) -> None:
        if not (user and user.strip()):
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            rec = {"ts": self._now().strftime("%Y-%m-%d %H:%M"),
                   "user": user.strip(), "assistant": (assistant or "").strip()}
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001 - 아카이브 실패가 대화를 깨면 안 된다
            pass

    def _load(self) -> list[dict]:
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except Exception:  # noqa: BLE001
            return []
        out = []
        for ln in lines[-_MAX_ENTRIES_SCANNED:]:
            try:
                out.append(json.loads(ln))
            except Exception:  # noqa: BLE001 - 깨진 줄은 건너뜀
                continue
        return out

    def search(self, query: str, k: int = 3, min_score: float = 0.08) -> list[dict]:
        """query와 겹치는 과거 턴 상위 k건. [{ts,user,assistant,score}]"""
        q = _bigrams(query)
        if not q:
            return []
        entries = self._load()
        scored = []
        n = len(entries)
        for i, e in enumerate(entries):
            text = f"{e.get('user', '')} {e.get('assistant', '')}"
            b = _bigrams(text)
            if not b:
                continue
            overlap = len(q & b) / len(q)
            recency = 0.05 * (i / n) if n else 0.0   # 최근일수록 소폭 가산
            score = overlap + recency
            if overlap >= min_score:
                scored.append((score, e))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [{**e, "score": round(s, 3)} for s, e in scored[:k]]

    def context_block(self, query: str, k: int = 3) -> str:
        """respond 주입용 발췌 블록. 관련 기억이 없으면 빈 문자열."""
        hits = self.search(query, k=k)
        if not hits:
            return ""
        lines = ["[장기 기억 — 과거 대화 중 관련 발췌. 도움이 되면 활용하고 아니면 무시:"]
        for h in hits:
            u = h["user"][:_SNIPPET]
            a = h["assistant"][:_SNIPPET]
            lines.append(f"  ({h['ts']}) 사용자: {u} / 자비스: {a}")
        lines.append("]")
        return "\n".join(lines) + "\n"
