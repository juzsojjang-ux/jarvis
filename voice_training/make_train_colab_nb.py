"""Generate voice_training/train_colab.ipynb (RVC v2 training, Colab/CUDA only).

Run once from the main venv to (re)emit the notebook; commit BOTH this script
and the generated train_colab.ipynb:
    ~/jarvis/.venv/bin/python voice_training/make_train_colab_nb.py
"""
from __future__ import annotations

from pathlib import Path

import nbformat as nbf

INTRO = (
    "# JARVIS RVC v2 training (Colab GPU only)\n\n"
    "Upload `dataset/` (40 kHz mono s16 WAV, **10-30 min CLEAN single-speaker vocals**,\n"
    "no music/reverb). Runtime -> Change runtime type -> **GPU (T4/A100)**.\n"
    "Mac MPS training is low-quality — do NOT train locally. Target ~150-300 epochs, batch ~40."
)
CLONE = (
    "!git clone https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI.git rvc\n"
    "%cd rvc\n"
    "!pip install -r requirements.txt\n"
    "!python tools/download_models.py"
)
PREPROCESS = (
    "# preprocess: sr=40000, n_cpu=4, exp=jarvis (dataset at /content/dataset)\n"
    "!python infer/modules/train/preprocess.py /content/dataset 40000 4 ./logs/jarvis True 3.0"
)
EXTRACT = (
    "# F0 (RMVPE) + HuBERT feature extraction (v2)\n"
    "!python infer/modules/train/extract/extract_f0_rmvpe.py 1 0 0 ./logs/jarvis True\n"
    "!python infer/modules/train/extract_feature_print.py cuda:0 1 0 ./logs/jarvis v2"
)
TRAIN = (
    "# train: ~150-300 epochs (-te), batch 40 (-bs), save every 25 (-se)\n"
    "!python infer/modules/train/train.py -e jarvis -sr 40k -f0 1 -bs 40 -te 250 -se 25 \\\n"
    "  -pg assets/pretrained_v2/f0G40k.pth -pd assets/pretrained_v2/f0D40k.pth "
    "-l 0 -c 0 -sw 1 -v v2"
)
INDEX = (
    "# build the faiss index, then download the two artifacts\n"
    "!python tools/train_index.py jarvis v2\n"
    "from google.colab import files\n"
    "files.download('logs/jarvis/added_IVF_jarvis_v2.index')\n"
    "files.download('assets/weights/jarvis.pth')"
)
OUTRO = (
    "## Install the result on the Mac\n\n"
    "Copy BOTH `jarvis.pth` + `added_IVF_jarvis_v2.index` into `~/jarvis/voice_models/`\n"
    "(so `rvc_model_path` / `rvc_index_path` resolve), then run JARVIS with\n"
    "`JARVIS_TTS_BACKEND=melotts JARVIS_VC_BACKEND=rvc python -m jarvis`."
)


def build_notebook() -> nbf.NotebookNode:
    nb = nbf.v4.new_notebook()
    nb.cells = [
        nbf.v4.new_markdown_cell(INTRO),
        nbf.v4.new_code_cell(CLONE),
        nbf.v4.new_code_cell(PREPROCESS),
        nbf.v4.new_code_cell(EXTRACT),
        nbf.v4.new_code_cell(TRAIN),
        nbf.v4.new_code_cell(INDEX),
        nbf.v4.new_markdown_cell(OUTRO),
    ]
    nb.metadata["accelerator"] = "GPU"
    nb.metadata["colab"] = {"provenance": []}
    nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3"}
    return nb


def main() -> str:
    out = Path(__file__).resolve().parent / "train_colab.ipynb"
    nb = build_notebook()
    nbf.write(nb, str(out))
    print(f"wrote {out} ({len(nb.cells)} cells)")
    return str(out)


if __name__ == "__main__":
    main()
