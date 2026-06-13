"""자가 코딩 — 두뇌가 새 스킬을 '직접' 만들고 검증한다.

기존엔 두뇌가 Write 도구로 ~/.jarvis/skills/<name>.py 를 손으로 써야 했다.
이 모듈은 그걸 1급 도구(create_skill)로 올린다: 코드를 받아 ①문법 검사 ②샌드박스
임포트로 TOOLS 계약 확인 ③통과하면 파일로 저장. 깨진 코드는 저장 전에 거른다.

판단·작성은 두뇌가 한다 — 여기서는 안전한 착지(검증·저장)만 책임진다.
"""
from __future__ import annotations

import ast
import importlib.util
import re
import tempfile
from pathlib import Path

SKILLS_DIR = Path.home() / ".jarvis" / "skills"
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")


def validate_code(code: str) -> tuple[bool, str]:
    """문법 + TOOLS 계약을 검증한다(파일로 저장하기 전)."""
    if not code or not code.strip():
        return False, "코드가 비어 있습니다."
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return False, f"문법 오류: {exc.msg} (줄 {exc.lineno})"
    # 샌드박스 임포트 — 모듈 레벨 실행이 깨지지 않는지 + TOOLS 모양 확인
    try:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "_probe_skill.py"
            p.write_text(code, encoding="utf-8")
            spec = importlib.util.spec_from_file_location("_probe_skill", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # 코드 실행
            tools = getattr(mod, "TOOLS", None)
            if not isinstance(tools, list) or not tools:
                return False, "모듈에 TOOLS 리스트가 없습니다(최소 1개 도구 필요)."
            for t in tools:
                if not isinstance(t, dict):
                    return False, "TOOLS 항목은 dict여야 합니다."
                for field in ("name", "description", "handler"):
                    if field not in t:
                        return False, f"TOOLS 항목에 '{field}'가 없습니다."
                if not callable(t["handler"]):
                    return False, "handler는 호출 가능한 함수여야 합니다."
    except Exception as exc:  # noqa: BLE001 - 임포트 단계의 모든 실패를 잡는다
        return False, f"코드 실행 검증 실패: {type(exc).__name__}: {exc}"
    return True, "검증 통과"


def save_skill(name: str, code: str, *, skills_dir: Path | None = None) -> tuple[bool, str]:
    """검증 후 ~/.jarvis/skills/<name>.py 로 저장. (성공?, 메시지)."""
    name = (name or "").strip().lower()
    if not _NAME_RE.match(name):
        return False, "이름은 영문 소문자/숫자/밑줄, 2~41자여야 합니다(예: coin_flip)."
    ok, msg = validate_code(code)
    if not ok:
        return False, msg
    d = skills_dir or SKILLS_DIR
    try:
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{name}.py"
        existed = path.exists()
        path.write_text(code, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return False, f"저장 실패: {exc}"
    verb = "갱신" if existed else "생성"
    return True, (f"스킬 '{name}' {verb} 완료 — 검증 통과. 자비스를 재시작하면 "
                  f"새 도구가 활성화됩니다. ({path})")


def list_skills(skills_dir: Path | None = None) -> list[str]:
    d = skills_dir or SKILLS_DIR
    try:
        return sorted(p.stem for p in d.glob("*.py") if not p.stem.startswith("_"))
    except Exception:  # noqa: BLE001
        return []
