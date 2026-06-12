"""사용자/자비스가 만든 '스킬'을 자동 로드 — 자가 기능 확장.

사용자가 "이런 기능 추가해줘"라고 하면, 연동된 LLM(두뇌)이 새 도구를
``~/.jarvis/skills/<이름>.py`` 에 코드로 써넣는다. 이 모듈이 시동 때 그 폴더의
``*.py`` 를 읽어 도구로 등록한다 — **다음 실행부터** 자비스가 그 능력을 갖는다
(즉시 실행이 아니라 재시작 시 로드 = 사용자가 코드를 검토할 여유).

스킬 파일 계약(LLM이 이 형식으로 작성):
    # ~/.jarvis/skills/coin.py
    async def handler(args):
        return "앞면"  # 문자열을 그대로 반환하면 된다
    TOOLS = [{
        "name": "coin_flip",
        "description": "동전을 던져 앞/뒤를 알려준다",
        "parameters": {"type": "object", "properties": {}},
        "handler": handler,
    }]

로드는 전부 방어적이다 — 스킬 하나가 깨져도 자비스 부팅을 막지 않는다."""
from __future__ import annotations

import importlib.util
import inspect
import logging
import os
from pathlib import Path
from typing import Any

from .registry import NeutralTool

_log = logging.getLogger(__name__)
DEFAULT_SKILLS_DIR = Path.home() / ".jarvis" / "skills"


def _wrap_handler(raw: Any):
    """스킬 handler(문자열/딕셔너리 반환, 동기/비동기)를 NeutralTool 계약으로 감싼다."""
    async def handler(args: dict) -> dict:
        try:
            res = raw(args or {})
            if inspect.isawaitable(res):
                res = await res
        except Exception as exc:  # noqa: BLE001 - 도구는 raise 금지
            res = f"스킬 실행 오류: {exc}"
        if isinstance(res, dict) and "content" in res:
            return res
        return {"content": [{"type": "text", "text": str(res)}]}
    return handler


def _load_file(path: Path) -> list[NeutralTool]:
    spec = importlib.util.spec_from_file_location(f"jarvis_skill_{path.stem}", path)
    if spec is None or spec.loader is None:
        return []
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # 스킬 코드 실행(모듈 레벨)
    out: list[NeutralTool] = []
    for spec_dict in getattr(mod, "TOOLS", []) or []:
        try:
            name = str(spec_dict["name"])
            desc = str(spec_dict.get("description", name))
            params = spec_dict.get("parameters") or {"type": "object", "properties": {}}
            raw = spec_dict["handler"]
        except (KeyError, TypeError):
            continue
        out.append(NeutralTool(name=name, description=desc, parameters=params,
                               handler=_wrap_handler(raw)))
    return out


def load_skill_tools(skills_dir: str | os.PathLike[str] | None = None) -> list[NeutralTool]:
    """``~/.jarvis/skills/*.py`` 의 모든 스킬 도구를 로드한다(실패는 건너뜀).

    기본 경로는 호출 시점에 DEFAULT_SKILLS_DIR을 읽는다 — 정의 시점 바인딩이면
    테스트의 monkeypatch(전역 격리)가 무력화된다."""
    if skills_dir is None:
        skills_dir = DEFAULT_SKILLS_DIR
    d = Path(os.path.expanduser(str(skills_dir)))
    if not d.is_dir():
        return []
    tools: list[NeutralTool] = []
    seen: set[str] = set()
    for py in sorted(d.glob("*.py")):
        if py.name.startswith("_"):
            continue
        try:
            for t in _load_file(py):
                if t.name in seen:
                    continue
                seen.add(t.name)
                tools.append(t)
        except Exception as exc:  # noqa: BLE001 - 스킬 하나가 부팅을 막으면 안 된다
            _log.warning("스킬 로드 실패 %s: %s", py.name, exc)
    if tools:
        _log.info("사용자 스킬 %d개 로드: %s", len(tools), ", ".join(t.name for t in tools))
    return tools
