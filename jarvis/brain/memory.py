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
        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = f"- {note}\n"
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line)
        self._text = (self._text + line) if self._text else line
