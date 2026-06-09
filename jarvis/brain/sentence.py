class SentenceChunker:
    """Accumulates streamed text deltas and emits completed Korean clauses/sentences.
    Boundaries: . ! ? … 。 ！ ？ ; or a Korean sentence-ender syllable followed by
    whitespace; or a max-char fallback for run-on streams with no punctuation."""

    PUNCT = {".", "!", "?", "…", "。", "！", "？"}
    KOREAN_ENDERS = {"다", "요", "죠", "까", "네", "군", "나"}
    WHITESPACE = {" ", "\n", "\t"}

    def __init__(self, max_chars: int = 60):
        self._buf = ""
        self._max = max_chars

    def feed(self, delta: str) -> list[str]:
        self._buf += delta
        buf = self._buf
        result: list[str] = []
        emitted = 0
        n = len(buf)
        for idx in range(n):
            ch = buf[idx]
            boundary = False
            if ch in self.PUNCT:
                boundary = True
            elif ch in self.KOREAN_ENDERS:
                nxt = buf[idx + 1] if idx + 1 < n else ""
                # Only a boundary when whitespace follows; a trailing ender is held
                # (more delta may arrive) and resolved by flush().
                if nxt in self.WHITESPACE:
                    boundary = True
            if boundary:
                seg = buf[emitted:idx + 1].strip()
                if seg:
                    result.append(seg)
                emitted = idx + 1

        remaining = buf[emitted:]
        if len(remaining) >= self._max:
            seg = remaining.strip()
            if seg:
                result.append(seg)
            emitted = n

        self._buf = buf[emitted:]
        return result

    def flush(self) -> str | None:
        seg = self._buf.strip()
        self._buf = ""
        return seg or None
