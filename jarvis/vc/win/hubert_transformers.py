"""fairseq-free contentvec 로더 — 윈도우 RVC용. transformers HubertModel로
content-vec-best를 로드해, rvc-python 파이프라인이 기대하는 hubert 인터페이스를
흉내낸다.

⚠️ WINDOWS-VERIFY-REQUIRED: 이 모듈은 맥에서 import되지 않는다.
  임베딩 차원(768-dim)은 동일 가중치라 이론상 동일하나, rvc-python 파이프라인
  연동(modules/vc/utils.py load_hubert, lib/jit/get_hubert.py)과의 실제 호환은
  윈도우 실기기에서 변환 결과를 들어보고 확인해야 한다.

fairseq 제거 이유:
  rvc-python 0.1.5가 fairseq==0.12.2를 hubert/contentvec 로딩 전용으로만 사용
  (checkpoint_utils.load_model_ensemble_and_task). 윈도우에서 fairseq 빌드는
  VS Build Tools + Python 3.10 강제 의존성이 생겨 설치가 어렵다.
  동일 가중치(lengyue233/content-vec-best)를 transformers HubertModel로 로드하면
  fairseq 없이 같은 임베딩을 얻는다(이론적으로; 실런타임 검증 필요).
"""
from __future__ import annotations

from typing import Any


class TransformersHubert:
    """rvc-python의 fairseq hubert 대체.

    .extract_features(source, padding_mask, output_layer) 를
    fairseq HubertModel과 유사 시그니처로 노출.

    ⚠️ WINDOWS-VERIFY-REQUIRED:
      - output_layer 매핑(어느 hidden state가 RVC jarvis.pth와 호환되는지)
        윈도우에서 fairseq 결과와 대조해 확정할 것.
      - 전통적으로 contentvec layer 9 또는 12 사용; 기본값 12로 설정.
    """

    def __init__(
        self,
        model_path_or_repo: str = "lengyue233/content-vec-best",
        device: str = "cpu",
    ):
        self._repo = model_path_or_repo
        self._device = device
        self._model: Any = None

    def _ensure(self) -> Any:
        if self._model is None:
            from transformers import HubertModel  # type: ignore[import-untyped]
            import torch  # noqa: F401

            self._model = (
                HubertModel.from_pretrained(self._repo).to(self._device).eval()
            )
        return self._model

    def extract_features(
        self,
        source: Any,
        padding_mask: Any = None,
        output_layer: int = 12,
    ) -> tuple[Any, Any]:
        """contentvec 임베딩 추출.

        Args:
            source: 오디오 텐서 (1D 또는 2D [batch, time]).
            padding_mask: 패딩 마스크 (fairseq 인터페이스 호환; 현재 무시됨).
            output_layer: 반환할 hidden state 레이어 인덱스 (0-based).
                          ⚠️ WINDOWS-VERIFY-REQUIRED: 올바른 레이어를 윈도우에서 확인할 것.

        Returns:
            (feats, padding_mask) — fairseq 반환값 형태 유지.
        """
        import torch

        model = self._ensure()
        with torch.no_grad():
            wav = source if hasattr(source, "dim") else torch.as_tensor(source)
            if wav.dim() == 1:
                wav = wav.unsqueeze(0)
            out = model(wav.to(self._device), output_hidden_states=True)
            # contentvec: 9번째 hidden state가 RVC가 쓰는 레이어(전통적으로 layer 9/12).
            # ⚠️ WINDOWS-VERIFY-REQUIRED: 정확한 레이어/투영은 윈도우에서 fairseq 결과와
            # 대조해 확정. fairseq 경로: hubert.extract_features(source, padding_mask,
            # output_layer=9) → 768-dim 벡터.
            if output_layer < len(out.hidden_states):
                feats = out.hidden_states[output_layer]
            else:
                feats = out.last_hidden_state
        return feats, padding_mask


def load_hubert_transformers(
    repo: str = "lengyue233/content-vec-best",
    device: str = "cpu",
) -> TransformersHubert:
    """TransformersHubert 인스턴스 반환. rvc-python의 load_hubert() 대체 진입점.

    윈도우 패치 방법 (setup_rvc_win.ps1 참고):
      rvc_python/modules/vc/utils.py 의 load_hubert() 를 이 함수 호출로 교체하거나,
      monkey-patch 방식으로 실행 전에 주입한다.
      ⚠️ WINDOWS-VERIFY-REQUIRED: 패치 방식과 인터페이스 확인 필요.
    """
    return TransformersHubert(repo, device)
