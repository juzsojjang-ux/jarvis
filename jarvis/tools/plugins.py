"""로컬 Claude Code 플러그인 발견 + 신뢰 레지스트리.

~/.jarvis/plugins/<name>/ 에 둔 플러그인만 로드한다(마켓플레이스 자동설치 없음 — SDK는
type:"local"만 지원). 제3자 코드이므로 기본 비신뢰: 플러그인이 제공하는 MCP 서버의 도구는
~/.jarvis/plugins/trust.json 에서 {"<plugin-dir>": true} 로 명시 승격하기 전까지 확인을 거친다.
어떤 함수도 예외를 올리지 않는다(플러그인 실패가 부팅/턴을 깨면 안 된다)."""
from __future__ import annotations

import json
import os
from pathlib import Path


def _root(path=None) -> Path:
    return Path(path) if path is not None else Path.home() / ".jarvis" / "plugins"


def discover(enabled: bool, path: str | os.PathLike | None = None) -> list[dict]:
    if not enabled:
        return []
    out: list[dict] = []
    try:
        for d in sorted(_root(path).iterdir()):
            if d.is_dir():
                out.append({"type": "local", "path": str(d)})
    except Exception:  # noqa: BLE001
        return []
    return out


def _servers_of(d: Path) -> set[str]:
    try:
        data = json.loads((d / ".mcp.json").read_text(encoding="utf-8"))
        return set((data.get("mcpServers") or {}).keys())
    except Exception:  # noqa: BLE001
        return set()


def plugin_servers(path=None) -> set[str]:
    servers: set[str] = set()
    try:
        for d in _root(path).iterdir():
            if d.is_dir():
                servers |= _servers_of(d)
    except Exception:  # noqa: BLE001
        pass
    return servers


def _trust_map(path=None) -> dict:
    try:
        return json.loads((_root(path) / "trust.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def trusted_servers(path=None) -> set[str]:
    trust = _trust_map(path)
    out: set[str] = set()
    try:
        for d in _root(path).iterdir():
            if d.is_dir() and trust.get(d.name) is True:
                out |= _servers_of(d)
    except Exception:  # noqa: BLE001
        pass
    return out
