import asyncio
import sys
import types

from jarvis.tools.builtin.voice_status import make_voice_status_tool


def _s(**kw):
    base = dict(vc_backend="auto", rvc_python=str(sys.executable),
                rvc_model_path="~/jarvis/voice_models/jarvis.pth",
                rvc_index_path="~/jarvis/voice_models/jarvis.index")
    base.update(kw)
    return types.SimpleNamespace(**base)


def _run(tool):
    result = tool.call({})
    if asyncio.iscoroutine(result):
        return asyncio.run(result)
    return result


def test_tool_contract_and_waiting_message(tmp_path):
    tool = make_voice_status_tool(_s(rvc_model_path=str(tmp_path / "absent.pth")))
    assert tool.name == "voice_status"
    assert hasattr(tool, "to_dict") and hasattr(tool, "call")
    assert "대기" in _run(tool)


def test_tool_active_message(tmp_path):
    pth = tmp_path / "jarvis.pth"
    pth.write_bytes(b"x")
    tool = make_voice_status_tool(_s(rvc_model_path=str(pth)))
    assert "활성화" in _run(tool)
