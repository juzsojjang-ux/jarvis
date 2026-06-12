"""Conversation history — keeps the last N (user, assistant) turns on disk.

Persists to JSONL (one turn per line).  All I/O is best-effort: read/write
errors are swallowed so a disk hiccup never crashes the voice pipeline.
Writes are atomic (write tmp → os.replace) to avoid partial-file corruption.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

# 모듈 전역 — 테스트는 conftest autouse fixture로 이 경로를 임시 폴더로 패치해
# 실제 홈 파일(~/.jarvis/history.jsonl)을 절대 건드리지 않는다.
DEFAULT_HISTORY_PATH = Path.home() / ".jarvis" / "history.jsonl"


class ConversationHistory:
    """Maintain a rolling window of the most-recent *max_turns* (user, assistant) pairs."""

    def __init__(
        self,
        path: Optional[Path] = None,
        max_turns: int = 10,
    ) -> None:
        if path is None:
            path = DEFAULT_HISTORY_PATH
        self._path = Path(path)
        self._max_turns = max_turns
        self.turns: list[tuple[str, str]] = []

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add(self, user: str, assistant: str) -> None:
        """Append one turn; skip if either side is blank; trim; persist."""
        if not (user and user.strip()) or not (assistant and assistant.strip()):
            return
        self.turns.append((user, assistant))
        self.turns = self.turns[-self._max_turns:]
        self._save()
        try:  # 장기 기억 아카이브(append-only) — 롤링 창과 별개로 영구 보관
            from .longmem import LongMemory  # noqa: PLC0415
            LongMemory().append(user, assistant)
        except Exception:  # noqa: BLE001 - 아카이브 실패가 대화를 깨면 안 된다
            pass

    def clear(self) -> None:
        """Wipe in-memory turns and overwrite the disk file with nothing."""
        self.turns = []
        self._save()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """Atomically write turns to JSONL.  Swallows all exceptions."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            lines = [
                json.dumps({"user": u, "assistant": a}, ensure_ascii=False)
                for u, a in self.turns
            ]
            tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            os.replace(tmp, self._path)
        except Exception:  # noqa: BLE001 — best-effort; never crash the voice pipeline
            pass

    def load(self) -> None:
        """Load turns from disk.  Missing file → empty; corrupt lines → skipped."""
        try:
            if not self._path.exists():
                return
            raw = self._path.read_text(encoding="utf-8")
            parsed: list[tuple[str, str]] = []
            for line in raw.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    u = obj.get("user", "")
                    a = obj.get("assistant", "")
                    if u and a:
                        parsed.append((u, a))
                except Exception:  # noqa: BLE001 — skip malformed line
                    pass
            self.turns = parsed[-self._max_turns:]
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Context injection
    # ------------------------------------------------------------------

    def as_context(self) -> str:
        """Return a context block for prepending to the first query after reconnect.

        Empty if no turns.  Format::

            [이전 대화 맥락 — 참고만, 다시 답하지 말 것]
            주인님: {user}
            자비스: {assistant}
            ...
            [현재 질문]

        Callers append the actual user question directly after the trailing newline.
        """
        if not self.turns:
            return ""
        lines = ["[이전 대화 맥락 — 참고만, 다시 답하지 말 것]"]
        for user, assistant in self.turns:
            lines.append(f"주인님: {user}")
            lines.append(f"자비스: {assistant}")
        lines.append("")
        lines.append("[현재 질문]")
        lines.append("")
        return "\n".join(lines)
