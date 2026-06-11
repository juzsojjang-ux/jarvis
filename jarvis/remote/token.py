"""원격 명령 토큰 — 아이폰 단축어가 Authorization: Bearer 헤더로 보낸다.
첫 부팅에 생성해 ~/.jarvis/remote_token(0600)에 둔다. 배너에는 경로만 안내
(토큰 원문을 stdout에 찍지 않는다)."""
from __future__ import annotations

import secrets
from pathlib import Path

DEFAULT_TOKEN_PATH = Path.home() / ".jarvis" / "remote_token"


def load_or_create_token(path: Path | None = None) -> str:
    p = Path(path) if path is not None else DEFAULT_TOKEN_PATH
    if p.exists():
        tok = p.read_text(encoding="utf-8").strip()
        if tok:
            return tok
    tok = secrets.token_urlsafe(32)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(tok + "\n", encoding="utf-8")
    p.chmod(0o600)
    return tok
