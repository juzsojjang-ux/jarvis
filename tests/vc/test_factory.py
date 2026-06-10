import sys
import types

import pytest

from jarvis.vc.factory import build_rvc_cmd, make_vc, vc_status
from jarvis.vc.null_vc import NullVC
from jarvis.vc.rvc import RVCConversion


def _s(**kw):
    base = dict(vc_backend="auto",
                rvc_python=str(sys.executable),  # existing path -> runtime "ready"
                rvc_model_path="~/jarvis/voice_models/jarvis.pth",
                rvc_index_path="~/jarvis/voice_models/jarvis.index",
                rvc_sample_rate=40000, rvc_index_rate=0.75, rvc_f0_up=0)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _model(tmp_path, name="jarvis.pth"):
    pth = tmp_path / name
    pth.write_bytes(b"x")
    return str(pth)


def test_make_vc_null():
    assert isinstance(make_vc(_s(vc_backend="null")), NullVC)


def test_auto_with_model_and_runtime_returns_rvc(tmp_path):
    vc = make_vc(_s(vc_backend="auto", rvc_model_path=_model(tmp_path)))
    assert isinstance(vc, RVCConversion)
    assert vc.sample_rate == 40000 and vc.index_rate == 0.75


def test_auto_without_model_falls_back_to_null(tmp_path):
    vc = make_vc(_s(vc_backend="auto", rvc_model_path=str(tmp_path / "absent.pth")))
    assert isinstance(vc, NullVC)


def test_auto_with_model_but_no_runtime_falls_back_to_null(tmp_path):
    vc = make_vc(_s(vc_backend="auto", rvc_model_path=_model(tmp_path),
                    rvc_python=str(tmp_path / "no-such-venv" / "python")))
    assert isinstance(vc, NullVC)


def test_force_rvc_with_model_returns_rvc(tmp_path):
    vc = make_vc(_s(vc_backend="rvc", rvc_model_path=_model(tmp_path)))
    assert isinstance(vc, RVCConversion)


def test_force_rvc_without_model_falls_back_to_null(tmp_path):
    vc = make_vc(_s(vc_backend="rvc", rvc_model_path=str(tmp_path / "absent.pth")))
    assert isinstance(vc, NullVC)


def test_rvc_picks_up_added_index(tmp_path):
    _model(tmp_path)
    added = tmp_path / "added_IVF_jarvis_v2.index"
    added.write_bytes(b"x")
    # configured index path must point inside tmp (and be absent) — otherwise a REAL
    # ~/jarvis/voice_models/jarvis.index on the machine wins the resolution order.
    vc = make_vc(_s(vc_backend="auto", rvc_model_path=str(tmp_path / "jarvis.pth"),
                    rvc_index_path=str(tmp_path / "jarvis.index")))
    assert isinstance(vc, RVCConversion) and vc.index_path == str(added)


def test_make_vc_unknown_raises():
    with pytest.raises(ValueError):
        make_vc(_s(vc_backend="bogus"))


def test_build_rvc_cmd_uses_runtime_and_shim(tmp_path):
    cmd = build_rvc_cmd(_s(rvc_python="/x/.venv-rvc/bin/python"))
    assert cmd[0] == "/x/.venv-rvc/bin/python"
    assert cmd[1].endswith("rvc_infer_cli.py")


def test_status_waiting_when_no_model(tmp_path):
    active, msg = vc_status(_s(vc_backend="auto", rvc_model_path=str(tmp_path / "absent.pth")))
    assert active is False and "대기" in msg


def test_status_runtime_missing(tmp_path):
    active, msg = vc_status(_s(vc_backend="auto", rvc_model_path=_model(tmp_path),
                               rvc_python=str(tmp_path / "no-venv" / "python")))
    assert active is False and "setup_rvc" in msg


def test_status_active(tmp_path):
    active, msg = vc_status(_s(vc_backend="auto", rvc_model_path=_model(tmp_path)))
    assert active is True and "활성화" in msg


def test_status_null_backend():
    active, msg = vc_status(_s(vc_backend="null"))
    assert active is False and "꺼짐" in msg
