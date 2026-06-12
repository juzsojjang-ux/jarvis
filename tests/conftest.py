"""테스트 전역 격리 — 대화 기억이 실제 홈 파일(~/.jarvis/history.jsonl)을
건드리지 않도록 모든 테스트에서 기본 경로를 임시 폴더로 돌린다. ConversationHistory
가 path=None일 때 이 상수를 읽으므로, 주입 없이 만든 두뇌도 자동으로 격리된다."""
import pytest


@pytest.fixture(autouse=True)
def _isolate_conversation_history(monkeypatch, tmp_path):
    monkeypatch.setattr("jarvis.brain.history.DEFAULT_HISTORY_PATH",
                        tmp_path / "history.jsonl", raising=False)
    monkeypatch.setattr("jarvis.brain.longmem.DEFAULT_LONGMEM_PATH",
                        tmp_path / "longmem.jsonl", raising=False)


@pytest.fixture(autouse=True)
def _isolate_user_skills(monkeypatch, tmp_path):
    # 실제 ~/.jarvis/skills(사용자/자비스 작성 스킬)이 도구 개수·동작 테스트에
    # 새지 않게 — 스킬 테스트는 load_skill_tools(경로)로 명시 주입한다.
    monkeypatch.setattr("jarvis.tools.skills.DEFAULT_SKILLS_DIR",
                        tmp_path / "no_skills", raising=False)
