"""Vocal isolation with audio-separator (BS-Roformer, CoreML on Apple Silicon).

Primary model: model_bs_roformer_ep_317_sdr_12.9755.ckpt via
CoreMLExecutionProvider. Fallback (if CoreML/Roformer fails): demucs-mlx
(`uv pip install demucs-mlx`; `python -m demucs_mlx --two-stems vocals in.wav`).
Always gate with check_env() first (verify CoreMLExecutionProvider).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROFORMER_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"


def check_env(runner=subprocess.run) -> bool:
    res = runner(["audio-separator", "--env_info"],
                 capture_output=True, text=True, check=True)
    out = (res.stdout or "") + (res.stderr or "")
    return "CoreMLExecutionProvider" in out


def build_separator(output_dir, model_dir):
    from audio_separator.separator import Separator
    sep = Separator(output_dir=str(output_dir), model_file_dir=str(model_dir),
                    output_format="WAV")
    sep.load_model(model_filename=ROFORMER_MODEL)
    return sep


def pick_vocal_stem(output_files: list[str]) -> str:
    for f in output_files:
        name = Path(f).name
        if "(Vocals)" in name or "_Vocals" in name or "vocals" in name.lower():
            return f
    raise ValueError(f"no vocal stem in {output_files}")


def separate_vocals(separator, in_wav) -> str:
    return pick_vocal_stem(separator.separate(str(in_wav)))
