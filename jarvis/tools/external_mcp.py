"""외부 MCP 서버 로더 — 프리미어 프로 같은 고차원 도구를 자비스 두뇌에 연결한다.

``~/.jarvis/mcp.json`` 에 서버를 선언하면 Claude(구독) 두뇌의 mcp_servers에
합류한다(claude-agent-sdk stdio 설정 형식). 보안: 외부 MCP 도구는 자동 허용되지
않는다 — 전권 모드가 아니면 호출마다 음성 확인을 거치고, 원격에선 전부 차단된다
(_can_use_tool의 기존 정책이 mcp__<외부>__* 를 그렇게 흘린다).

형식:
    {"servers": {"premiere-pro": {"command": "node",
                                  "args": ["/path/dist/index.js"],
                                  "env": {}}}}

로드는 방어적 — 파일이 없거나 깨져도 빈 dict(자비스 부팅을 막지 않는다)."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

_log = logging.getLogger(__name__)
DEFAULT_MCP_CONFIG_PATH = Path.home() / ".jarvis" / "mcp.json"


def load_external_servers(path: str | os.PathLike[str] | None = None) -> dict[str, dict]:
    """claude-agent-sdk mcp_servers 형식의 {이름: stdio설정} dict를 반환한다."""
    p = Path(os.path.expanduser(str(path if path is not None else DEFAULT_MCP_CONFIG_PATH)))
    try:
        if not p.is_file():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _log.warning("외부 MCP 설정을 읽지 못했습니다: %s", p)
        return {}
    out: dict[str, dict] = {}
    for name, cfg in (data.get("servers") or {}).items():
        if not isinstance(cfg, dict):
            continue
        cmd = cfg.get("command")
        if not isinstance(name, str) or not isinstance(cmd, str) or not cmd:
            continue
        if name == "jarvis":
            continue  # 내장 인프로세스 서버 이름은 예약(덮어쓰기 금지)
        args = [str(a) for a in (cfg.get("args") or [])]
        env = {str(k): str(v) for k, v in (cfg.get("env") or {}).items()}
        out[name] = {"type": "stdio", "command": cmd, "args": args, "env": env}
    if out:
        _log.info("외부 MCP 서버 %d개 연결: %s", len(out), ", ".join(out))
    return out
