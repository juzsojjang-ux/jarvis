# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for JARVIS lightweight-core distributable.
#
# PLATFORM NOTES
# ==============
# macOS:  pyinstaller packaging/jarvis.spec --noconfirm
#   Produces: dist/JARVIS.app  (bundle) + dist/JARVIS (onedir)
#   SIGNING: needs Apple Developer ID codesign + notarize (see docs/PACKAGING.md)
#   WITHOUT signing: right-click → Open bypasses Gatekeeper.
#
# Windows: pyinstaller packaging/jarvis.spec --noconfirm   (run in Windows)
#   Produces: dist\JARVIS\JARVIS.exe
#   SIGNING: EV cert for SmartScreen (see docs/PACKAGING.md)
#
# WHAT IS NOT BUNDLED
# ===================
# - .venv-pocket / .venv-rvc / .venv-xtts / .venv-tts (multi-GB torch venvs)
#   → RVC JARVIS-voice is an optional post-install (see docs/PACKAGING.md)
# - Whisper model (~1.5 GB) — downloaded to ~/.cache/huggingface on first run
# - MLX (Apple-only, requires arm64 Metal) — bundled but only runs on M-series Macs;
#   distributable defaults to faster-whisper STT on non-MLX targets.

import importlib.util
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Repository root (one directory above this spec file)
# ---------------------------------------------------------------------------
SPEC_DIR = Path(SPECPATH)          # noqa: F821  (PyInstaller injects SPECPATH)
REPO_ROOT = SPEC_DIR.parent

# ---------------------------------------------------------------------------
# Helper: safe data tuple — skips missing paths instead of crashing spec eval
# ---------------------------------------------------------------------------
def _data(src: str | Path, dest: str) -> tuple[str, str] | None:
    p = Path(src)
    if p.exists():
        return (str(p), dest)
    print(f"[jarvis.spec] WARNING: data source not found, skipping: {p}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# Core data files
# ---------------------------------------------------------------------------
datas_raw = [
    # Persona prompt (large, loaded at runtime via settings.persona_path)
    _data(REPO_ROOT / "jarvis" / "brain" / "persona_ko.md", "jarvis/brain"),

    # HUD overlay HTML (served by OrbServer)
    _data(REPO_ROOT / "jarvis" / "hud" / "orb.html", "jarvis/hud"),

    # Silero VAD ONNX model (~2.3 MB, wake-word voice activity detection)
    _data(REPO_ROOT / "voice_models" / "silero_vad.onnx", "voice_models"),

    # JARVIS voice (torch-free ONNX RVC) — bundled so the cloned timbre works out of
    # the box on macOS AND Windows. jarvis.onnx = synthesizer (~105MB),
    # vec-768-layer-12.onnx = contentvec embedder (~360MB).
    _data(REPO_ROOT / "voice_models" / "jarvis.onnx", "voice_models"),
    _data(REPO_ROOT / "voice_models" / "vec-768-layer-12.onnx", "voice_models"),

    # Setup UI HTML (first-run provider selection screen)
    _data(REPO_ROOT / "jarvis" / "setup" / "index.html", "jarvis/setup"),
]

# ---------------------------------------------------------------------------
# mlx_whisper data assets (mel_filters.npz, tiktoken vocab files)
# These are loaded by mlx_whisper/audio.py and tokenizer.py at runtime;
# PyInstaller only bundles .py files, not data assets sitting next to them.
# ---------------------------------------------------------------------------
_mlx_whisper_spec = importlib.util.find_spec("mlx_whisper")
if _mlx_whisper_spec and _mlx_whisper_spec.submodule_search_locations:
    _mlx_whisper_root = Path(list(_mlx_whisper_spec.submodule_search_locations)[0])
    _mlx_whisper_assets = _mlx_whisper_root / "assets"
    if _mlx_whisper_assets.exists():
        datas_raw.append((str(_mlx_whisper_assets), "mlx_whisper/assets"))
        print(f"[jarvis.spec] mlx_whisper assets: {_mlx_whisper_assets}")
    else:
        print(f"[jarvis.spec] WARNING: mlx_whisper/assets not found", file=sys.stderr)
else:
    print("[jarvis.spec] INFO: mlx_whisper not installed — skipping assets", file=sys.stderr)

# ---------------------------------------------------------------------------
# MLX Metal shader library (macOS Apple Silicon only)
# mlx.core loads mlx.metallib at C-extension init time via a relative rpath.
# Inside the frozen bundle that rpath breaks unless we copy the lib/ directory
# to a place that mlx.core can find relative to itself.
# Destination "mlx/lib" mirrors the installed layout: mlx/lib/mlx.metallib
# ---------------------------------------------------------------------------
_mlx_spec = importlib.util.find_spec("mlx")
if _mlx_spec and _mlx_spec.submodule_search_locations:
    _mlx_root = Path(list(_mlx_spec.submodule_search_locations)[0])
    _mlx_lib = _mlx_root / "lib"
    if _mlx_lib.exists():
        datas_raw.append((str(_mlx_lib), "mlx/lib"))
        _metallib = _mlx_lib / "mlx.metallib"
        if _metallib.exists():
            print(f"[jarvis.spec] MLX metallib found: {_metallib} "
                  f"({_metallib.stat().st_size / 1_048_576:.0f} MB)")
        else:
            print("[jarvis.spec] WARNING: mlx/lib exists but mlx.metallib not found.",
                  file=sys.stderr)
    else:
        print(f"[jarvis.spec] WARNING: mlx lib/ dir not found at {_mlx_lib}",
              file=sys.stderr)
else:
    print("[jarvis.spec] INFO: mlx not installed — skipping metallib bundle "
          "(Windows build or non-MLX venv)", file=sys.stderr)

# ---------------------------------------------------------------------------
# claude-agent-sdk bundled Node CLI
# Locate programmatically so the spec works even if the venv path changes.
# The binary is ~220 MB (Node.js executable wrapping the claude CLI) so it
# WILL be included in the bundle.  Users who prefer the subscription brain
# need this; Gemini/GPT users don't, but we bundle it unconditionally.
# ---------------------------------------------------------------------------
_sdk_spec = importlib.util.find_spec("claude_agent_sdk")
if _sdk_spec and _sdk_spec.submodule_search_locations:
    _sdk_root = Path(list(_sdk_spec.submodule_search_locations)[0])
    _bundled_dir = _sdk_root / "_bundled"
    _claude_bin = _bundled_dir / "claude"
    if _claude_bin.exists():
        # Preserve the _bundled/ subdirectory structure so the SDK finds it
        # at its expected relative path inside the installed package.
        datas_raw.append((str(_bundled_dir), "claude_agent_sdk/_bundled"))
        print(f"[jarvis.spec] claude-agent-sdk bundled CLI found: {_claude_bin} "
              f"({_claude_bin.stat().st_size / 1_048_576:.0f} MB)")
    else:
        print(f"[jarvis.spec] WARNING: claude-agent-sdk _bundled/claude not found "
              f"at {_claude_bin} — subscription brain will not work in bundle.",
              file=sys.stderr)
else:
    print("[jarvis.spec] WARNING: claude_agent_sdk not installed — "
          "subscription brain unavailable in bundle.", file=sys.stderr)

# Drop None entries (missing optional files)
datas = [d for d in datas_raw if d is not None]

# ---------------------------------------------------------------------------
# Hidden imports
# Brain backends are selected at runtime via JARVIS_BRAIN_PROVIDER env var
# or first-run setup; PyInstaller won't trace through the factory's if-chains.
# ---------------------------------------------------------------------------
hiddenimports = [
    # Brain backends
    "jarvis.brain.subscription",
    "jarvis.brain.gemini",
    "jarvis.brain.openai_brain",
    "jarvis.brain.codex_auth",
    "jarvis.brain.claude",         # "api" backend (Anthropic API key path)

    # TTS backends (selected by tts_backend setting)
    "jarvis.tts.edge_tts_backend",
    "jarvis.tts.system_say",

    # STT backends
    "jarvis.stt.faster_whisper_stt",   # Windows / Linux default
    "jarvis.stt.mlx_whisper",          # macOS Apple Silicon default

    # Tools
    "jarvis.tools.win_control",        # Windows-only but import must not fail on Mac

    # Third-party runtime deps imported lazily
    "edge_tts",
    "edge_tts.communicate",
    "faster_whisper",
    "soundfile",
    "sounddevice",
    "onnxruntime",
    "onnxruntime.capi",
    "onnxruntime.capi.onnxruntime_inference_collection",

    # Google Gemini SDK
    "google.genai",
    "google.genai.types",

    # OpenAI
    "openai",
    "openai._models",

    # Keyring — backends are discovered via entrypoints at runtime
    "keyring",
    "keyring.backends",
    "keyring.backends.null",
    "keyring.backends.fail",
    "keyring.backends.chainer",
    "keyring.backends.macOS",          # macOS Keychain
    "keyring.backends.SecretService",  # Linux
    "keyring.backends.Windows",        # Windows Credential Locker
    "keyring.backends.kwallet",
    "keyring.backends.libsecret",

    # pydantic / pydantic-settings introspection
    "pydantic",
    "pydantic_settings",

    # Audio / soxr
    "soxr",
    "numpy",
    "pynput",
    "pynput.keyboard",
    "pynput.mouse",

    # MLX (Apple Silicon only — will be present in Mac venv)
    # mlx._reprlib_fix is a Python shim that mlx/__init__.py imports; PyInstaller
    # doesn't trace it because it's imported inside mlx.core's C extension init path.
    "mlx",
    "mlx.core",
    "mlx._reprlib_fix",
    "mlx.utils",
    "mlx.nn",
    "mlx.nn.layers",
    "mlx.optimizers",
    # mlx_whisper submodules (imported lazily by MLXWhisperSTT)
    "mlx_whisper",
    "mlx_whisper.audio",
    "mlx_whisper.decoding",
    "mlx_whisper.tokenizer",
    "mlx_whisper.transcribe",
    "mlx_whisper.load_models",
    "mlx_whisper.whisper",
    "mlx_whisper.timing",
    "mlx_whisper.writers",

    # Anthropic SDK + MCP
    "anthropic",
    "mcp",
    "mcp.client",
    "mcp.client.stdio",
    "mcp.client.sse",

    # Standard-library modules sometimes missed by PyInstaller
    "asyncio",
    "importlib.util",
    "importlib.metadata",

    # pyautogui / mss (screen capture on non-Mac)
    "pyautogui",
    "mss",
    # Note: mss.base does not exist as a separate importable module in mss>=9.0
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
block_cipher = None   # no encryption; None is the modern default

a = Analysis(
    [str(REPO_ROOT / "packaging" / "jarvis_launch.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Heavy torch-based voice venvs — NOT bundled (post-install optional upgrade)
        "torch",
        "torchaudio",
        "torchvision",
        "TTS",                 # coqui XTTS
        "transformers",        # only pulled in by optional voice path
        "faiss",
        "noisereduce",
        "demucs",
        # Testing
        "pytest",
        "ruff",
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)   # noqa: F821

# ---------------------------------------------------------------------------
# EXE (onedir — works on both macOS and Windows)
# ---------------------------------------------------------------------------
exe = EXE(                                               # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="JARVIS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # 메모리 절약 — UPX 압축은 폭발 위험
    console=True,       # Keep console: JARVIS prints status lines
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,   # None = native arch of build machine
    codesign_identity=None,      # Set to your Apple Developer ID for signing
    entitlements_file=None,      # Add entitlements.plist for Hardened Runtime
)

# ---------------------------------------------------------------------------
# COLLECT (onedir layout — all files in dist/JARVIS/)
# ---------------------------------------------------------------------------
coll = COLLECT(                                          # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,  # 메모리 절약 — UPX 압축은 폭발 위험
    upx_exclude=[],
    name="JARVIS",
)

# ---------------------------------------------------------------------------
# macOS .app BUNDLE
# Only built when running on macOS; harmless on Windows (PyInstaller ignores
# BUNDLE if the platform check fails, but we guard with sys.platform anyway).
# ---------------------------------------------------------------------------
if sys.platform == "darwin":
    app = BUNDLE(                                        # noqa: F821
        coll,
        name="JARVIS.app",
        icon=None,          # TODO: supply an .icns file via icon="path/to/jarvis.icns"
        bundle_identifier="com.jarvis.assistant",
        version="0.1.0",
        info_plist={
            # Human-readable name shown in Finder / Spotlight
            "CFBundleName": "JARVIS",
            "CFBundleDisplayName": "JARVIS Assistant",
            "CFBundleVersion": "0.1.0",
            "CFBundleShortVersionString": "0.1.0",

            # macOS REQUIRES these usage strings before granting hardware access.
            # The OS shows these strings in the permission dialog.
            "NSMicrophoneUsageDescription":
                "JARVIS needs microphone access to hear your voice commands.",
            "NSScreenCaptureUsageDescription":
                "JARVIS can take screenshots for screen-aware assistance.",

            # Accessibility API (reading/clicking UI elements on your behalf)
            # NOTE: NSAccessibility cannot be requested via Info.plist alone —
            # the user must grant it manually in System Settings →
            # Privacy & Security → Accessibility after first launch.
            # This key is advisory only (some tools check it):
            "NSAppleEventsUsageDescription":
                "JARVIS uses Accessibility APIs to assist with on-screen tasks.",

            # Prevent macOS from treating this as a background-only process
            "LSUIElement": False,

            # Allow the app to run without a signed Python interpreter
            # (only relevant when using Hardened Runtime + notarization)
            # "com.apple.security.cs.allow-unsigned-executable-memory": True,
            # "com.apple.security.cs.disable-library-validation": True,
        },
    )
