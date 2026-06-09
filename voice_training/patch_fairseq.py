"""Make fairseq checkpoint loading work on torch>=2.6 (.venv-rvc).

torch 2.6 flipped torch.load's default to weights_only=True; fairseq's
load_checkpoint_to_cpu then fails to unpickle hubert_base.pt (it contains the
fairseq.data.dictionary.Dictionary global). hubert_base.pt comes from the standard
RVC distribution and is trusted, so we load with weights_only=False.

Idempotent. Run with the .venv-rvc interpreter:
    ~/jarvis/.venv-rvc/bin/python ~/jarvis/voice_training/patch_fairseq.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

OLD = 'state = torch.load(f, map_location=torch.device("cpu"))'
NEW = ('state = torch.load(f, map_location=torch.device("cpu"), weights_only=False)'
       '  # JARVIS patch: torch>=2.6 defaults weights_only=True; hubert_base.pt is trusted')


def main() -> None:
    spec = importlib.util.find_spec("fairseq")
    if spec is None or not spec.submodule_search_locations:
        raise SystemExit("fairseq not importable here — run with the .venv-rvc interpreter")
    path = Path(spec.submodule_search_locations[0]) / "checkpoint_utils.py"
    src = path.read_text(encoding="utf-8")
    if NEW in src:
        print(f"already patched: {path}")
        return
    if OLD not in src:
        raise SystemExit(f"pattern not found (fairseq changed?): {path}")
    path.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
    print(f"patched: {path}")


if __name__ == "__main__":
    main()
