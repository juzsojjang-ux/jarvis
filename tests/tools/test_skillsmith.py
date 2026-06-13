"""자가 코딩(create_skill 백엔드) — 검증이 깨진 코드를 거르고 좋은 코드만 저장."""
from __future__ import annotations

from jarvis.tools import skillsmith

GOOD = '''
async def handler(args):
    return "앞면"
TOOLS = [{"name": "coin_flip", "description": "동전 던지기",
          "parameters": {"type": "object", "properties": {}}, "handler": handler}]
'''


def test_validate_good_code():
    ok, msg = skillsmith.validate_code(GOOD)
    assert ok, msg


def test_validate_syntax_error():
    ok, msg = skillsmith.validate_code("def handler(args)\n  return 1")
    assert not ok and "문법" in msg


def test_validate_missing_tools():
    ok, msg = skillsmith.validate_code("x = 1\n")
    assert not ok and "TOOLS" in msg


def test_validate_handler_not_callable():
    bad = ('TOOLS = [{"name": "x", "description": "d", '
           '"parameters": {}, "handler": "notfunc"}]')
    ok, msg = skillsmith.validate_code(bad)
    assert not ok and "handler" in msg


def test_validate_import_time_crash():
    ok, msg = skillsmith.validate_code("raise RuntimeError('boom')\nTOOLS=[]")
    assert not ok


def test_save_good_skill(tmp_path):
    ok, msg = skillsmith.save_skill("coin_flip", GOOD, skills_dir=tmp_path)
    assert ok and (tmp_path / "coin_flip.py").exists() and "생성" in msg


def test_save_rejects_bad_name(tmp_path):
    ok, msg = skillsmith.save_skill("Coin Flip!", GOOD, skills_dir=tmp_path)
    assert not ok and "이름" in msg


def test_save_rejects_broken_code_before_writing(tmp_path):
    ok, msg = skillsmith.save_skill("broken", "def f(:", skills_dir=tmp_path)
    assert not ok and not (tmp_path / "broken.py").exists()


def test_save_update_existing(tmp_path):
    skillsmith.save_skill("coin_flip", GOOD, skills_dir=tmp_path)
    ok, msg = skillsmith.save_skill("coin_flip", GOOD, skills_dir=tmp_path)
    assert ok and "갱신" in msg


def test_list_skills(tmp_path):
    skillsmith.save_skill("alpha", GOOD, skills_dir=tmp_path)
    skillsmith.save_skill("beta", GOOD, skills_dir=tmp_path)
    assert skillsmith.list_skills(tmp_path) == ["alpha", "beta"]
