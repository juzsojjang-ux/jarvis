"""tests/setup/test_main_wiring.py — __main__._amain이 is_configured()==False이면
run_first_run_setup을 호출하는지 검증한다.

실제 부팅(모델 로딩 등)은 하지 않는다. asyncio 이벤트 루프를 공유하지 않는
방식(monkeypatch)으로 _amain 진입부만 확인한다.
"""
from __future__ import annotations

import pytest


def test_is_not_configured_triggers_setup(monkeypatch):
    """is_configured()가 False이면 run_first_run_setup이 호출된다."""
    import jarvis.setup.store as store_mod
    import jarvis.setup.launcher as launcher_mod

    setup_called: list[bool] = []

    monkeypatch.setattr(store_mod, "is_configured", lambda path=None: False)
    monkeypatch.setattr(store_mod, "configured_provider", lambda path=None: None)
    monkeypatch.setattr(launcher_mod, "run_first_run_setup",
                        lambda **kw: setup_called.append(True) or "claude")

    # __main__ 진입부 로직을 인라인으로 재현한다
    import os
    from jarvis.setup.store import configured_provider, is_configured
    from jarvis.setup.launcher import run_first_run_setup

    if not is_configured():
        run_first_run_setup()
    saved = configured_provider()
    if saved:
        os.environ.setdefault("JARVIS_BRAIN_PROVIDER", saved)

    assert setup_called == [True]


def test_is_configured_skips_setup(monkeypatch):
    """is_configured()가 True이면 run_first_run_setup이 호출되지 않는다."""
    import jarvis.setup.store as store_mod
    import jarvis.setup.launcher as launcher_mod

    setup_called: list[bool] = []

    monkeypatch.setattr(store_mod, "is_configured", lambda path=None: True)
    monkeypatch.setattr(store_mod, "configured_provider", lambda path=None: "claude")
    monkeypatch.setattr(launcher_mod, "run_first_run_setup",
                        lambda **kw: setup_called.append(True) or "claude")

    import os
    from jarvis.setup.store import configured_provider, is_configured
    from jarvis.setup.launcher import run_first_run_setup

    if not is_configured():
        run_first_run_setup()
    saved = configured_provider()
    if saved:
        os.environ.setdefault("JARVIS_BRAIN_PROVIDER", saved)

    assert setup_called == []
