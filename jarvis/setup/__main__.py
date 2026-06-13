"""`python -m jarvis.setup` — 첫 실행 이후 설정(보이스/마이크 키/두뇌/이름) 변경 UI.

트레이/메뉴막대의 '설정' 메뉴가 이걸 별도 프로세스로 띄운다. 저장은 setup.json에
기록되고, 자비스를 재시작하면 적용된다(실행 중인 자비스는 건드리지 않는다)."""
from jarvis.setup.launcher import run_settings

if __name__ == "__main__":
    run_settings()
