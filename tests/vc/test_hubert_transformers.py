"""fairseq-free TransformersHubert 래퍼 구조 테스트.

실제 torch/transformers 모델은 다운로드하지 않는다 — monkeypatch로 가짜 주입.
이 테스트는 래퍼의 lazy-load 동작과 extract_features 인터페이스만 검증한다.

⚠️ WINDOWS-VERIFY-REQUIRED: 실제 임베딩 품질 및 rvc-python 파이프라인 연동은
  윈도우 실기기에서 검증해야 한다.
"""
import contextlib
import sys
import types

from jarvis.vc.win.hubert_transformers import TransformersHubert, load_hubert_transformers


def test_lazy_load_and_extract(monkeypatch):
    """가짜 torch + transformers 주입 → lazy load + extract_features 동작 확인."""
    calls: dict = {}

    class _FakeOut:
        def __init__(self):
            self.hidden_states = ["h0"] * 13  # 인덱스 0-12
            self.last_hidden_state = "last"

    class _FakeModel:
        def to(self, d):
            return self

        def eval(self):
            return self

        def __call__(self, wav, output_hidden_states=False):
            calls["called"] = True
            return _FakeOut()

    class _FakeHM:
        @staticmethod
        def from_pretrained(repo):
            calls["repo"] = repo
            return _FakeModel()

    class _FakeTensor:
        """1D 텐서처럼 동작하는 가짜 객체."""

        def dim(self):
            return 1

        def unsqueeze(self, n):
            return self

        def to(self, d):
            return self

    fake_torch = types.SimpleNamespace(
        no_grad=lambda: contextlib.nullcontext(),
        as_tensor=lambda x: _FakeTensor(),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(
        sys.modules, "transformers", types.SimpleNamespace(HubertModel=_FakeHM)
    )

    h = TransformersHubert("repo-x")
    feats, mask = h.extract_features(_FakeTensor(), output_layer=12)

    assert calls["repo"] == "repo-x"
    assert calls["called"] is True
    assert feats == "h0"  # hidden_states[12]
    assert mask is None  # padding_mask 그대로 반환


def test_lazy_load_deferred_until_extract(monkeypatch):
    """_model은 extract_features 첫 호출 전까지 None 이어야 한다."""
    h = TransformersHubert("lengyue233/content-vec-best")
    assert h._model is None  # 아직 로드 안 됨


def test_fallback_to_last_hidden_state(monkeypatch):
    """output_layer가 hidden_states 범위를 초과하면 last_hidden_state 반환."""
    calls: dict = {}

    class _FakeOut:
        def __init__(self):
            self.hidden_states = ["h0", "h1"]  # 인덱스 0, 1 만 있음
            self.last_hidden_state = "last_fallback"

    class _FakeModel:
        def to(self, d):
            return self

        def eval(self):
            return self

        def __call__(self, wav, output_hidden_states=False):
            return _FakeOut()

    class _FakeHM:
        @staticmethod
        def from_pretrained(repo):
            return _FakeModel()

    class _FakeTensor:
        def dim(self):
            return 1

        def unsqueeze(self, n):
            return self

        def to(self, d):
            return self

    fake_torch = types.SimpleNamespace(
        no_grad=lambda: contextlib.nullcontext(),
        as_tensor=lambda x: _FakeTensor(),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(
        sys.modules, "transformers", types.SimpleNamespace(HubertModel=_FakeHM)
    )

    h = TransformersHubert("repo-x")
    feats, _ = h.extract_features(_FakeTensor(), output_layer=99)
    assert feats == "last_fallback"


def test_load_helper_returns_instance():
    """load_hubert_transformers()가 TransformersHubert 반환 확인."""
    assert isinstance(load_hubert_transformers(), TransformersHubert)


def test_load_helper_passes_repo_and_device():
    """repo/device 인수가 인스턴스에 저장되는지 확인."""
    h = load_hubert_transformers(repo="my/repo", device="cuda")
    assert h._repo == "my/repo"
    assert h._device == "cuda"
