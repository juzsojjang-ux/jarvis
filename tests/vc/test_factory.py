import types

import pytest

from jarvis.vc.factory import make_vc
from jarvis.vc.null_vc import NullVC
from jarvis.vc.rvc import RVCConversion


def _s(**kw):
    base = dict(vc_backend="null",
                rvc_model_path="~/jarvis/voice_models/jarvis.pth",
                rvc_index_path="~/jarvis/voice_models/jarvis.index",
                rvc_sample_rate=40000, rvc_index_rate=0.75, rvc_f0_up=0)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_make_vc_null():
    assert isinstance(make_vc(_s(vc_backend="null")), NullVC)


def test_make_vc_rvc_when_model_present(tmp_path):
    pth = tmp_path / "jarvis.pth"
    pth.write_bytes(b"x")
    idx = tmp_path / "jarvis.index"
    idx.write_bytes(b"x")
    vc = make_vc(_s(vc_backend="rvc", rvc_model_path=str(pth), rvc_index_path=str(idx)))
    assert isinstance(vc, RVCConversion) and vc.sample_rate == 40000 and vc.index_rate == 0.75


def test_make_vc_rvc_falls_back_to_null_when_model_absent(tmp_path):
    # spec 8.4 bootstrap: the JARVIS voice path must run BEFORE Colab produces jarvis.pth.
    vc = make_vc(_s(vc_backend="rvc", rvc_model_path=str(tmp_path / "absent.pth")))
    assert isinstance(vc, NullVC)


def test_make_vc_unknown_raises():
    with pytest.raises(ValueError):
        make_vc(_s(vc_backend="bogus"))
