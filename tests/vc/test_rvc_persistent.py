import sys
from pathlib import Path

import numpy as np

from jarvis.vc.rvc_persistent import PersistentRVC

# Fake persistent worker honoring the line protocol: READY once, then for each
# CONVERT request writes a 0.2s 330Hz sine at 40k to <out_wav> and replies OK.
FAKE_WORKER = """
import sys, numpy as np, soundfile as sf
print("READY", flush=True)
for line in sys.stdin:
    parts = line.rstrip("\\n").split("\\t")
    if len(parts) != 3 or parts[0] != "CONVERT":
        print("ERR bad request", flush=True); continue
    sr = 40000
    t = np.arange(int(0.2 * sr)) / sr
    sf.write(parts[2], (0.1 * np.sin(2*np.pi*330*t)).astype("float32"), sr)
    print("OK", flush=True)
"""


def _vc(tmp_path):
    fake = tmp_path / "fake_worker.py"
    fake.write_text(FAKE_WORKER)
    return PersistentRVC("m.pth", "m.index", sample_rate=40000,
                         worker_cmd=[sys.executable, str(fake)])


def test_warm_and_convert_reuse_one_worker(tmp_path):
    vc = _vc(tmp_path)
    vc.warm()
    proc1 = vc._proc
    out = vc.convert(np.zeros(44100, dtype=np.float32), in_rate=44100)
    assert out.dtype == np.float32
    assert abs(out.shape[0] - int(0.2 * 40000)) <= 64
    assert vc.sample_rate == 40000
    vc.convert(np.zeros(1000, dtype=np.float32), in_rate=16000)
    assert vc._proc is proc1  # persistent: same worker, no reload
    vc.close()


def test_env_carries_model_and_params(tmp_path):
    vc = PersistentRVC(str(tmp_path / "jarvis.pth"), str(tmp_path / "a.index"),
                       index_rate=0.9, f0_up=-12,
                       worker_cmd=[sys.executable, "x.py"])
    env = vc._env()
    assert env["JARVIS_RVC_MODEL"].endswith("jarvis.pth")
    assert env["JARVIS_RVC_INDEX"].endswith("a.index")
    assert env["JARVIS_RVC_INDEX_RATE"] == "0.9"
    assert env["JARVIS_RVC_F0_UP"] == "-12"


def test_worker_error_raises(tmp_path):
    bad = tmp_path / "bad_worker.py"
    bad.write_text('print("READY", flush=True)\n'
                   'import sys\n'
                   'for line in sys.stdin: print("ERR boom", flush=True)\n')
    vc = PersistentRVC("m.pth", None, worker_cmd=[sys.executable, str(bad)])
    try:
        vc.convert(np.zeros(100, dtype=np.float32), in_rate=40000)
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "boom" in str(exc)
    finally:
        vc.close()


def test_worker_path_exists():
    from jarvis.vc.rvc_persistent import WORKER_PATH
    assert Path(WORKER_PATH).is_file()
