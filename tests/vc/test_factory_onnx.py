"""make_vc factory tests for the 'onnx' backend."""
import types

from jarvis.vc.factory import make_vc
from jarvis.vc.null_vc import NullVC
from jarvis.vc.onnx_rvc import OnnxRVCConversion


def _s(tmp_path, m_name="jarvis.onnx", cv_name="vec-768-layer-12.onnx", create=True, **kw):
    if create:
        m = tmp_path / m_name
        m.write_bytes(b"x")
        cv = tmp_path / cv_name
        cv.write_bytes(b"x")
    else:
        m = tmp_path / m_name
        cv = tmp_path / cv_name
    base = dict(
        vc_backend="onnx",
        onnx_model_path=str(m),
        onnx_contentvec_path=str(cv),
        rvc_sample_rate=40000,
        rvc_f0_up=0,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_make_vc_onnx_returns_onnx_rvc_when_models_present(tmp_path):
    vc = make_vc(_s(tmp_path))
    assert isinstance(vc, OnnxRVCConversion)
    assert vc.sample_rate == 40000
    assert vc.f0_up == 0


def test_make_vc_onnx_uses_f0_up(tmp_path):
    vc = make_vc(_s(tmp_path, rvc_f0_up=-12))
    assert isinstance(vc, OnnxRVCConversion)
    assert vc.f0_up == -12


def test_make_vc_onnx_missing_model_falls_back_to_null(tmp_path):
    vc = make_vc(_s(tmp_path, create=False))
    assert isinstance(vc, NullVC)


def test_make_vc_onnx_missing_contentvec_falls_back_to_null(tmp_path):
    # Only synthesizer present, contentvec absent
    m = tmp_path / "jarvis.onnx"
    m.write_bytes(b"x")
    s = types.SimpleNamespace(
        vc_backend="onnx",
        onnx_model_path=str(m),
        onnx_contentvec_path=str(tmp_path / "absent_vec.onnx"),
        rvc_sample_rate=40000,
        rvc_f0_up=0,
    )
    vc = make_vc(s)
    assert isinstance(vc, NullVC)
