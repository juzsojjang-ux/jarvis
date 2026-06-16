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

# Windows 기본 콘솔 인코딩(cp1252)에서 이 spec의 한글/화살표(→) print가
# UnicodeEncodeError로 빌드를 통째로 깨뜨린다 → stdout/stderr를 UTF-8(+replace)로 강제.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

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

    # HUD orb — 알파 영상(엔진별): mac=HEVC .mov, win=VP9 .webm. 검정 배경이 빠져있어
    # WebKit(WKWebView)에서도 검정 박스 없이 표시된다. (SVG 휘도키는 video에 안 먹음)
    _data(REPO_ROOT / "jarvis" / "hud" / "assets" / "orb-alpha.mov", "jarvis/hud/assets"),
    _data(REPO_ROOT / "jarvis" / "hud" / "assets" / "orb-alpha.webm", "jarvis/hud/assets"),

    # Silero VAD ONNX model (~2.3 MB, wake-word voice activity detection)
    _data(REPO_ROOT / "voice_models" / "silero_vad.onnx", "voice_models"),

    # JARVIS voice (torch-free ONNX RVC) — bundled so the cloned timbre works out of
    # the box on macOS AND Windows. jarvis.onnx = synthesizer (~105MB),
    # vec-768-layer-12.onnx = contentvec embedder (~360MB).
    _data(REPO_ROOT / "voice_models" / "jarvis.onnx", "voice_models"),
    _data(REPO_ROOT / "voice_models" / "vec-768-layer-12.onnx", "voice_models"),

    # Setup UI HTML (first-run provider selection screen)
    _data(REPO_ROOT / "jarvis" / "setup" / "index.html", "jarvis/setup"),

    # --- 하이브리드 '개인용 풀음성 업그레이드' 자산 ---------------------------
    # 사용자가 셋업 UI에서 업그레이드를 누르면 upgrade_full_voice 스크립트가
    # 이 자산들로 torch venv(Pocket / RVC)를 깐다. 번들 자체는 실행하지 않는다.
    #   • voice_full_src/jarvis : 워커 venv가 import할 jarvis 소스(.pth로 연결)
    #   • voice_full_assets     : 음색 모델/레퍼런스(개인용과 동일 자산)
    #   • upgrade_full_voice.*   : 설치 스크립트(번들 루트)
    _data(REPO_ROOT / "jarvis", "voice_full_src/jarvis"),
    _data(REPO_ROOT / "voice_models" / "jarvis_en_ref.wav", "voice_full_assets"),
    _data(REPO_ROOT / "voice_models" / "jarvis_ref.wav", "voice_full_assets"),
    _data(REPO_ROOT / "voice_models" / "jarvis.pth", "voice_full_assets"),
    _data(REPO_ROOT / "voice_models" / "jarvis.index", "voice_full_assets"),
    _data(REPO_ROOT / "packaging" / "upgrade_full_voice.sh", "."),
    _data(REPO_ROOT / "packaging" / "upgrade_full_voice.ps1", "."),
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

    # HUD 오버레이 + 상태 아이콘(런타임에 플랫폼별로 spawn — 정적 추적 안 됨)
    "jarvis.hud.overlay_mac",
    "jarvis.hud.overlay_win",
    "jarvis.hud.tray",
    "pystray",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",

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

# 윈도우 투명 오버레이(pywebview) — [winhud] 설치돼 있을 때만 번들. 없으면
# overlay_win이 Edge 앱모드로 폴백한다. find_spec로 설치 여부를 확인해, pywebview
# 없는 환경(맥)에서 hiddenimports 미스로 경고 나는 걸 피한다.
if importlib.util.find_spec("webview") is not None:
    hiddenimports += [
        "webview", "webview.platforms", "webview.platforms.winforms",
        "webview.platforms.edgechromium", "clr_loader", "pythonnet",
    ]
    print("[jarvis.spec] pywebview found — 윈도우 투명 오버레이 번들")

# macOS 네이티브 투명 오버레이(pyobjc WKWebView) — [hud] 설치돼 있을 때만 번들.
# overlay_mac이 'from WebKit import WKWebView' 등을 하는데 런타임에 -m로 spawn돼
# 정적 추적이 안 되므로 pyobjc 프레임워크 모듈을 명시 수집한다(없으면 'No module
# named WebKit'로 오버레이가 죽는다). 윈도우/미설치 환경에선 건너뛴다.
if sys.platform == "darwin" and importlib.util.find_spec("WebKit") is not None:
    hiddenimports += ["WebKit", "Cocoa", "Quartz", "objc",
                      "Foundation", "AppKit", "CoreFoundation",
                      # 권한 확인·요청(AXIsProcessTrustedWithOptions) — permissions.py
                      "ApplicationServices", "HIServices"]
    print("[jarvis.spec] pyobjc WebKit found — 맥 투명 오버레이 번들")

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
    icon=str(REPO_ROOT / "packaging" / "jarvis.ico"),  # Windows .exe 아이콘
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
        icon=str(REPO_ROOT / "packaging" / "jarvis.icns"),  # 자비스 오브 앱 아이콘
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
