"""Make MeloTTS importable for KOREAN-ONLY use on macOS.

MeloTTS imports every language module unconditionally, and japanese.py
hard-requires `mecab-python3` (the `MeCab` package). But Korean g2pkk needs
`python-mecab-ko` (the `mecab` package), and on a case-INSENSITIVE macOS
filesystem `MeCab/` and `mecab/` are the SAME directory — the two cannot
coexist. We only use Korean, so:

  - japanese.py:  `import MeCab` becomes optional (MeCab = None). japanese.py
    still imports (english.py needs its `distribute_phone`), but Japanese g2p
    (which we never call) would fail at call time — fine.
  - cleaner.py:   import `japanese` optionally too (belt-and-suspenders).

Idempotent. Run INSIDE .venv-tts:
    ~/jarvis/.venv-tts/bin/python ~/jarvis/voice_training/patch_melotts.py
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_PATCHES = [
    (
        "text/japanese.py",
        'try:\n    import MeCab\nexcept ImportError as e:\n'
        '    raise ImportError("Japanese requires mecab-python3 and unidic-lite.") from e',
        "try:\n    import MeCab\nexcept ImportError:\n"
        "    MeCab = None  # Korean-only build; Japanese g2p is never called.",
    ),
    (
        "text/japanese.py",
        "_TAGGER = MeCab.Tagger()",
        "_TAGGER = MeCab.Tagger() if MeCab is not None else None",
    ),
    (
        "text/cleaner.py",
        "from . import chinese, japanese, english, chinese_mix, korean, french, spanish",
        "from . import chinese, english, chinese_mix, korean, french, spanish\n"
        "try:\n    from . import japanese\nexcept ImportError:\n    japanese = None",
    ),
]


def main() -> None:
    spec = importlib.util.find_spec("melo")
    if spec is None or not spec.submodule_search_locations:
        raise SystemExit("melo not importable here — run with the .venv-tts interpreter")
    root = Path(spec.submodule_search_locations[0])
    for rel, old, new in _PATCHES:
        path = root / rel
        src = path.read_text(encoding="utf-8")
        if new in src:
            print(f"already patched: {path}")
            continue
        if old not in src:
            print(f"skip (pattern not found): {path}")
            continue
        path.write_text(src.replace(old, new, 1), encoding="utf-8")
        print(f"patched: {path}")


if __name__ == "__main__":
    main()
