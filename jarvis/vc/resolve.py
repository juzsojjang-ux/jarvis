"""Drop-in detection for the JARVIS RVC model.

Pure path logic so the assistant can AUTO-activate the JARVIS timbre the moment a
trained model is dropped into ``voice_models/`` — the user's only required action.
Both the model and its index are matched forgivingly (exact name first, then a glob)
because RVC training emits files like ``jarvis.pth`` / ``added_<hash>.index`` whose
exact names vary. The index is OPTIONAL: RVC converts on the ``.pth`` alone (the index
only improves timbre similarity).
"""
from __future__ import annotations

import os
from pathlib import Path


def expand(p: str | os.PathLike[str]) -> str:
    return os.path.expanduser(str(p))


def resolve_model_path(model_path: str | os.PathLike[str]) -> str | None:
    """Return a usable ``.pth`` or None.

    Prefers the configured path (e.g. ``~/jarvis/voice_models/jarvis.pth``); if that
    exact file is absent, returns the first ``*.pth`` in the same directory so the user
    can drop a differently-named export and still have it picked up.
    """
    p = Path(expand(model_path))
    if p.is_file():
        return str(p)
    d = p.parent
    if d.is_dir():
        cands = sorted(d.glob("*.pth"))
        if cands:
            return str(cands[0])
    return None


def resolve_index_path(
    model_path: str | os.PathLike[str],
    index_path: str | os.PathLike[str] | None,
) -> str | None:
    """Return a usable ``.index`` or None (index is optional).

    Order: the configured index path if it exists, else ``added_*.index`` (RVC's
    default export name) next to the model, else any ``*.index`` there, else None.
    """
    if index_path:
        ip = Path(expand(index_path))
        if ip.is_file():
            return str(ip)
    d = Path(expand(model_path)).parent
    if d.is_dir():
        for pattern in ("added_*.index", "*.index"):
            cands = sorted(d.glob(pattern))
            if cands:
                return str(cands[0])
    return None
