"""PyInstaller entry-point shim for JARVIS.

This file is the ``script`` argument in jarvis.spec.  It cannot use
``python -m jarvis`` (PyInstaller does not support the -m flag) so we
import the package's main() directly.

Nothing else should live here — all real logic is in jarvis/__main__.py.
"""
from jarvis.__main__ import main

if __name__ == "__main__":
    main()
