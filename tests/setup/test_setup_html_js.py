"""SETUP_HTML 인라인 JS 구문 가드.

첫실행 설정 페이지의 <script>에 JS SyntaxError(예: 같은 스코프 `let` 중복 선언)가
있으면 페이지의 JS가 통째로 실행 안 돼 모든 버튼이 무반응이 된다 — 기설정 기기는
설정창을 안 띄워 못 잡고, 신규 기기에서만 터진다(실제로 v2.1.2에서 발생).
파이썬 테스트는 인라인 JS를 안 돌려봐서 놓쳤다. 이 테스트가 그 부류를 막는다.
"""
import re
import shutil
import subprocess

import pytest

from jarvis.setup.server import SETUP_HTML


def _extract_js() -> str:
    m = re.search(r"<script>\n(.*?)</script>", SETUP_HTML, re.S)
    assert m, "SETUP_HTML에 <script> 블록이 없습니다"
    return m.group(1)


def test_setup_js_parses_with_node(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node 미설치 — JS 구문검사 건너뜀")
    f = tmp_path / "setup.js"
    f.write_text(_extract_js(), encoding="utf-8")
    r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, f"설정 페이지 JS 구문 오류:\n{r.stderr}"
