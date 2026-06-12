"""자가진단 — 어떤 점검도 raise하지 않고, 보고서가 이상을 정확히 표기하는지."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from jarvis.core.selfcheck import (
    Check, _check_crash_log, _check_error_log, format_report, run_checks,
    summary_line,
)


def test_run_checks_never_raises_without_orch():
    checks = run_checks()
    assert checks, "점검 결과가 비면 안 된다"
    assert all(isinstance(c, Check) for c in checks)


def test_crash_log_counts_today_only(tmp_path: Path):
    log = tmp_path / "crash.log"
    log.write_text(
        "=== CRASH 2026-06-11T20:41:12 ===\nTraceback...\n"
        "=== CRASH 2026-06-12T20:41:12 ===\nTraceback...\n",
        encoding="utf-8")
    c = _check_crash_log(now=datetime(2026, 6, 12, 21, 0), log_dir=tmp_path)
    assert not c.ok and "1회" in c.detail


def test_crash_log_clean_today(tmp_path: Path):
    (tmp_path / "crash.log").write_text(
        "=== CRASH 2026-06-11T20:41:12 ===\n", encoding="utf-8")
    c = _check_crash_log(now=datetime(2026, 6, 12, 21, 0), log_dir=tmp_path)
    assert c.ok


def test_error_log_flags_recent_errors(tmp_path: Path):
    (tmp_path / "jarvis.log").write_text(
        "[HUD] ok\n[오류] Command failed with exit code 1\n", encoding="utf-8")
    c = _check_error_log(log_dir=tmp_path)
    assert not c.ok and "Command failed" in c.detail


def test_format_report_marks_bad_items():
    checks = [Check("두뇌", True, "SubscriptionBrain"),
              Check("마이크", False, "입력 장치가 없습니다")]
    rep = format_report(checks)
    assert "✓ 두뇌" in rep and "✗ 마이크" in rep and "이상 1건" in rep


def test_summary_line_all_ok():
    s = summary_line([Check("a", True, ""), Check("b", True, "")])
    assert "모두 정상" in s


def test_summary_line_names_failures():
    s = summary_line([Check("두뇌", False, ""), Check("b", True, "")])
    assert "두뇌" in s and "1개 이상" in s


def test_orch_checks_capture_brain_error():
    class FakeBrain:
        last_error = "boom"
    class FakeOrch:
        brain = FakeBrain()
        settings = None
        hud = None
        usage = None
    checks = run_checks(FakeOrch())
    brain_check = next(c for c in checks if c.name == "두뇌")
    assert not brain_check.ok and "boom" in brain_check.detail
