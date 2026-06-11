"""RVC 공개 자산(contentvec·rmvpe) 확보 — 없으면 HuggingFace에서 1회 다운로드·캐시.
jarvis.pth/index는 앱 동봉이라 여기서 안 받는다. 다운로더 주입형(테스트는 가짜)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

DEFAULT_ASSET_DIR = Path.home() / ".jarvis" / "rvc_assets"

# (로컬 파일명, HF repo_id, repo 내 파일경로)
_ASSETS = [
    ("content-vec-best.safetensors", "lengyue233/content-vec-best", "pytorch_model.bin"),
    ("rmvpe.pt", "lj1995/VoiceConversionWebUI", "rmvpe.pt"),
]


def ensure_assets(
    asset_dir: Path | None = None,
    downloader: Optional[Callable[[str, str, Path], Path]] = None,
) -> dict:
    """필요한 자산이 로컬에 있도록 보장. 반환: {name: local_path}. downloader 주입형."""
    d = Path(asset_dir) if asset_dir else DEFAULT_ASSET_DIR
    d.mkdir(parents=True, exist_ok=True)
    dl = downloader or _hf_download
    out = {}
    for local_name, repo_id, repo_file in _ASSETS:
        target = d / local_name
        if not target.exists():
            try:
                dl(repo_id, repo_file, target)
            except Exception:  # noqa: BLE001 - 다운로드 실패는 호출부가 처리(폴백/안내)
                continue
        if target.exists():
            out[local_name] = target
    return out


def _hf_download(repo_id: str, repo_file: str, target: Path) -> Path:
    from huggingface_hub import hf_hub_download  # type: ignore[import-untyped]
    import shutil

    src = hf_hub_download(repo_id=repo_id, filename=repo_file)
    shutil.copy(src, target)
    return target


def missing_assets(asset_dir: Path | None = None) -> list[str]:
    """로컬에 없는 자산 이름 목록 반환."""
    d = Path(asset_dir) if asset_dir else DEFAULT_ASSET_DIR
    return [n for n, _, _ in _ASSETS if not (d / n).exists()]
