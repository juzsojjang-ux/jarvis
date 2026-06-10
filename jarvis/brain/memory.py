import re
from pathlib import Path


class MemoryStore:
    def __init__(self, path: Path):
        self._path = Path(path)
        self._text = ""

    def load(self) -> None:
        self._text = self._path.read_text(encoding="utf-8") if self._path.exists() else ""

    def text(self) -> str:
        return self._text

    def remember(self, note: str) -> None:
        note = note.strip()
        if not note:
            return
        if self._is_duplicate(note):  # 같은/포함 관계 사실은 다시 적지 않는다
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = f"- {note}\n"
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line)
        self._text = (self._text + line) if self._text else line

    @staticmethod
    def _norm(s: str) -> str:
        # 비교용 정규화: 소문자·구두점 제거·공백 전체 제거. 의미 같은데 표기만
        # 다른 중복을 잡기 위함(완벽한 의미비교가 아니라 값싼 휴리스틱).
        # 공백을 모두 없애면 한국어 어절 붙여쓰기 변형도 잡는다.
        s = re.sub(r"[^\w]", "", s.lower())
        return s

    def _is_duplicate(self, note: str) -> bool:
        n = self._norm(note)
        if not n:
            return False
        for line in self._text.splitlines():
            existing = self._norm(line.lstrip("- ").strip())
            if not existing:
                continue
            if n == existing or n in existing or existing in n:
                return True
        return False
