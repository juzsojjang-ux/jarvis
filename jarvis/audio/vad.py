from __future__ import annotations

import shutil
import urllib.request
from pathlib import Path

import numpy as np

# silero-vad v5 공식 저장소의 ONNX 가중치(~2.3 MB). 1회 받아두면 완전 오프라인.
SILERO_URL = (
    "https://raw.githubusercontent.com/snakers4/silero-vad/master/"
    "src/silero_vad/data/silero_vad.onnx"
)


def ensure_silero_model(path: Path) -> Path:
    path = Path(path).expanduser()
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    try:
        # 타임아웃 필수: 첫 부팅이 먹통 네트워크(캡티브 포털 등)에서 OS TCP
        # 타임아웃(수 분)만큼 멈추면 PTT까지 같이 인질로 잡힌다.
        with urllib.request.urlopen(SILERO_URL, timeout=15) as resp, open(tmp, "wb") as f:
            shutil.copyfileobj(resp, f)
        tmp.rename(path)
    except BaseException:
        tmp.unlink(missing_ok=True)  # 중단/실패 시 부분 파일 잔류 방지
        raise
    return path


class SileroVAD:
    """silero-vad v5 ONNX — 16 kHz, 512샘플 윈도우당 말소리 확률(0~1).
    onnxruntime 세션은 1스레드 고정: 이 프로젝트는 OMP 다중스레드로 faiss가
    세그폴트한 전력이 있다(같은 프로세스에 mlx도 산다)."""

    WINDOW = 512
    # v5 입력 규격: 직전 청크의 마지막 64샘플(컨텍스트)을 새 512샘플 앞에 붙인
    # 576샘플을 먹인다. 동적 shape라 512만 넣어도 에러 없이 돌지만 확률이
    # ~0.001로 망가진다(실측: 같은 음성 512만=0.001 vs 576=1.000).
    CONTEXT = 64

    def __init__(self, model_path: Path, sample_rate: int = 16000):
        import onnxruntime as ort  # 모델 없는 테스트 환경에서 모듈 import는 가볍게

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        self._sess = ort.InferenceSession(
            str(Path(model_path).expanduser()), sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self._sr = np.array(sample_rate, dtype=np.int64)
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._ctx = np.zeros(self.CONTEXT, dtype=np.float32)

    def reset(self) -> None:
        # 게이트 닫힘 동안 30ms마다 불리므로 재할당 대신 제자리 초기화.
        self._state.fill(0.0)
        self._ctx.fill(0.0)

    def prob(self, frame: np.ndarray) -> float:
        x = np.asarray(frame, dtype=np.float32).reshape(-1)
        inp = np.concatenate([self._ctx, x]).reshape(1, -1)
        out, self._state = self._sess.run(
            None, {"input": inp, "state": self._state, "sr": self._sr}
        )
        # copy: 호출자 버퍼의 뷰를 잡아두면 큰 원본 배열이 통째로 살아남는다.
        self._ctx = x[-self.CONTEXT:].copy()
        return float(out[0, 0])
