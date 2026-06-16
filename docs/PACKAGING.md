# JARVIS — Packaging & Distribution Guide

This document covers building JARVIS as a standalone distributable, the design rationale for what's included vs. excluded, runtime requirements, distribution gates (signing/notarization), and the optional post-install voice-clone upgrade.

---

## Lightweight-Core Rationale

JARVIS has two distinct runtime footprints:

| Layer | What it contains | Bundleable? |
|---|---|---|
| **Lightweight core** | STT (faster-whisper / mlx-whisper), TTS (edge-tts), brain (subscription/Gemini/GPT), tools, wake word | **Yes** |
| **Voice-clone chain** | `.venv-pocket`, `.venv-rvc`, `.venv-xtts`, `.venv-tts` — heavy conflicting Torch builds (each 3-6 GB) | **No** |

The voice-clone venvs contain multiple mutually-incompatible Torch versions pinned for ARM64 Metal, CUDA, and CoreML. Merging them into a single bundle is not feasible and would produce a 10-20 GB artifact. The distributable therefore ships the lightweight core and documents the voice-clone upgrade as a post-install optional step.

---

## Build Tooling

| File | Purpose |
|---|---|
| `build/jarvis_launch.py` | Thin PyInstaller entry-point shim (`from jarvis.__main__ import main; main()`) |
| `build/jarvis.spec` | PyInstaller spec (both platforms) |
| `build/build_mac.sh` | macOS build script |
| `build/build_win.ps1` | Windows build script |

---

## What's Inside the Lightweight Bundle

### Bundled
- `jarvis/` Python package (all submodules except heavy torch paths)
- `jarvis/brain/persona_ko.md` — JARVIS persona prompt
- `jarvis/hud/orb.html` — HUD overlay UI
- `voice_models/silero_vad.onnx` — Silero VAD model (~2.3 MB, wake-word voice activity detection)
- `claude_agent_sdk/_bundled/claude` — Bundled Node.js CLI (~220 MB) for the Claude subscription brain
- All Python dependencies from `.venv` (edge-tts, onnxruntime, sounddevice, pynput, etc.)

### NOT Bundled (downloads on first run)
| File | Size | Location |
|---|---|---|
| Whisper model (e.g. `whisper-large-v3-turbo`) | ~1.5 GB | `~/.cache/huggingface/hub/` |
| faster-whisper CT2 model (Windows) | ~1-3 GB | `~/.cache/huggingface/hub/` |

The first-run STT warm-up triggers the download automatically via `huggingface_hub`. After that, set `HF_HUB_OFFLINE=1` for fully offline operation.

### NOT Bundled (post-install optional — RVC voice upgrade)
- `voice_models/jarvis.pth` — Trained RVC voice model
- `voice_models/jarvis.index` — FAISS index for timbre matching
- `.venv-rvc` / `.venv-pocket` / `.venv-xtts` — Voice clone runtimes
- contentvec / rmvpe checkpoint (downloaded by RVC on first run, ~200 MB)

---

## Building: macOS

### Prerequisites
- macOS (Apple Silicon or Intel x86-64)
- Python 3.11 installed
- JARVIS main venv at `.venv`:
  ```sh
  python3.11 -m venv .venv
  . .venv/bin/activate
  pip install -e ".[dev]"
  ```

### Build
```sh
cd /path/to/jarvis
bash build/build_mac.sh
```

Output:
- `dist/JARVIS/` — onedir bundle (for testing)
- `dist/JARVIS.app` — macOS app bundle

### Quick Test (unsigned)
```sh
# Allow the quarantine flag if needed (developer only):
xattr -dr com.apple.quarantine dist/JARVIS.app
open dist/JARVIS.app
# Or run the binary directly:
dist/JARVIS.app/Contents/MacOS/JARVIS
```

---

## Building: Windows

### Prerequisites
- Windows 10/11 (x64)
- Python 3.11 from python.org
- JARVIS main venv:
  ```powershell
  python -m venv .venv
  .venv\Scripts\pip install -e ".[dev]"
  ```
- **Note:** The `claude-agent-sdk` bundled CLI is a macOS arm64 binary and does not run on Windows. For the subscription brain on Windows, install the Claude CLI separately: https://claude.ai/download

### Build
```powershell
.\build\build_win.ps1
```

Output: `dist\JARVIS\JARVIS.exe`

---

## macOS First-Run Permissions

JARVIS requires these macOS permissions on first launch:

| Permission | What triggers it | How to grant |
|---|---|---|
| **Microphone** | First time you speak | macOS system dialog (auto-prompted) |
| **Screen Recording** | Screen-capture tool call | macOS system dialog (auto-prompted) |
| **Accessibility** | Keyboard/mouse automation tools | System Settings → Privacy & Security → Accessibility → add JARVIS manually |
| **Automation / AppleEvents** | Controlling other apps | Prompted per-app on first use |

**Without Accessibility permission**, keyboard/mouse tools will silently fail. There is no way to pre-grant it programmatically; the user must add the app manually.

---

## Windows First-Run Permissions

| Permission | What triggers it | How to grant |
|---|---|---|
| **Microphone** | STT on first run | Windows microphone dialog (auto-prompted) |
| **Screen capture** | mss screenshot | No permission needed on Windows |
| **UAC elevation** | Not required for normal use | — |

---

## Signing Gates — macOS

Without signing and notarization, Gatekeeper shows "JARVIS is damaged and can't be opened" on user Macs.

| Gate | Cost | Who provides it |
|---|---|---|
| Apple Developer Program | **$99/yr** | You (developer) |
| Code-signing (Developer ID Application) | Included with Developer account | Xcode / codesign CLI |
| Notarization | Included with Developer account | xcrun notarytool |
| Hardened Runtime entitlements | Free (config only) | `build/entitlements.plist` (create per Apple docs) |

### Signing workflow (after build)
```sh
# 1. Sign (replace with your actual identity from 'security find-identity -v -p codesigning')
codesign --force --deep \
  --sign "Developer ID Application: Your Name (TEAMID)" \
  --entitlements build/entitlements.plist \
  --options runtime \
  dist/JARVIS.app

# 2. Zip for notarization
ditto -c -k --keepParent dist/JARVIS.app dist/JARVIS.zip

# 3. Submit to Apple's notarization service
xcrun notarytool submit dist/JARVIS.zip \
  --apple-id your@email.com \
  --password <APP_SPECIFIC_PASSWORD> \
  --team-id TEAMID \
  --wait

# 4. Staple the ticket so it works offline
xcrun stapler staple dist/JARVIS.app

# 5. Wrap in a DMG for distribution
hdiutil create -volname JARVIS -srcfolder dist/JARVIS.app \
  -ov -format UDZO dist/JARVIS-0.1.0-macOS.dmg
```

**Required entitlements** (`build/entitlements.plist` — create this file):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>com.apple.security.cs.allow-jit</key>
  <false/>
  <key>com.apple.security.device.microphone</key>
  <true/>
  <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
  <true/>
  <key>com.apple.security.cs.disable-library-validation</key>
  <true/>
</dict>
</plist>
```

> **Note:** `disable-library-validation` is required because PyInstaller bundles native `.so` files that macOS would otherwise reject under Hardened Runtime.

---

## Signing Gates — Windows

Without a code-signing certificate, Windows Defender SmartScreen shows "Windows protected your PC" and prevents running.

| Gate | Cost | Who provides it |
|---|---|---|
| OV (Organization Validation) code-signing cert | ~$100-300/yr | DigiCert, Sectigo, Comodo |
| EV (Extended Validation) code-signing cert | ~$300-600/yr | DigiCert, Sectigo |

**OV certs** suppress the Unknown Publisher dialog but SmartScreen reputation takes months to accumulate. **EV certs** provide immediate SmartScreen trust. For a new product reaching end-users, an EV cert is strongly recommended.

```powershell
# After obtaining cert.pfx:
signtool sign /fd SHA256 /p12 cert.pfx /p <password> `
  /tr http://timestamp.sectigo.com /td SHA256 `
  dist\JARVIS\JARVIS.exe
```

---

## What Works vs. What's Gated

| Feature | Status | Gate |
|---|---|---|
| Claude subscription brain | Works (bundled Node CLI) | Requires Claude Pro/Max subscription login |
| Gemini brain | Works | Requires `JARVIS_GEMINI_API_KEY` env var |
| GPT brain | Works | Requires OpenAI API key or ChatGPT subscription |
| edge-tts (British JARVIS voice) | Works | Free, online TTS (Microsoft Edge) |
| Wake word (silero VAD) | Works | ONNX model bundled |
| Push-to-talk | Works | — |
| Whisper STT (mlx — Mac) | Works after first run | Downloads ~1.5 GB model on first run |
| Whisper STT (faster-whisper — Windows) | Works after first run | Downloads model on first run |
| HUD overlay | Works | — |
| Remote server (iPhone Shortcuts) | Works | — |
| Unsigned app on developer Mac | Works (right-click → Open) | — |
| Distribution to end-users (Mac) | **BLOCKED** | Apple Developer ID ($99/yr) + notarization |
| Distribution to end-users (Windows) | **BLOCKED** | EV code-signing cert (~$300-600/yr) |
| Pocket JARVIS-clone voice | Post-install (first-run "Pocket 설치") | Needs Python 3.11 + ~GB torch; **no Hugging Face token** — weights (CC-BY-4.0) are fetched token-free from the `voice-weights` release and loaded offline, scoped to the Pocket worker so Whisper STT still downloads normally |
| RVC JARVIS-clone voice | Not included | Post-install upgrade (see below) |
| macOS Accessibility permission | Works | Manual grant in System Settings |

---

## Optional Post-Install: RVC JARVIS-Voice Upgrade

After installing the distributable, users can optionally install the JARVIS voice clone (RVC timbre conversion):

1. **Drop the model files** into `~/jarvis/voice_models/`:
   - `jarvis.pth` — trained RVC model
   - `jarvis.index` — FAISS timbre index

2. **Set up the RVC venv** (Apple Silicon only — not supported in the distributable):
   ```sh
   # From the repo root:
   python3.11 -m venv .venv-rvc
   .venv-rvc/bin/pip install mlx-rvc  # or: git+https://github.com/lextoumbourou/mlx-rvc
   ```
   On Windows: see `docs/WINDOWS_VOICE.md`.

3. **Configure JARVIS** (`~/.jarvis/config.json` or env vars):
   ```
   JARVIS_TTS_BACKEND=melotts
   JARVIS_VC_BACKEND=auto
   ```

4. JARVIS will auto-detect `jarvis.pth` on startup and switch to the voice clone.

The RVC runtime is intentionally NOT bundled because:
- It requires a separate heavy Torch-based venv (3-6 GB)
- The Torch version conflicts with other bundled dependencies
- RVC is only useful after the user obtains a trained `jarvis.pth` (via Colab training)

---

## Troubleshooting

### "JARVIS is damaged and can't be opened" (macOS)
The app is not notarized. Either:
- Right-click → Open (developer/tester only)
- `xattr -dr com.apple.quarantine dist/JARVIS.app`
- Or sign + notarize (production distribution)

### "Windows protected your PC" (Windows SmartScreen)
The EXE is unsigned. Either:
- Click "More info → Run anyway" (tester only)
- Sign with an EV certificate (production)

### STT hangs on first run
The Whisper model is downloading (~1.5 GB). Wait for the download to complete. If you're on a slow connection, pre-download with:
```sh
python -c "from huggingface_hub import snapshot_download; snapshot_download('mlx-community/whisper-large-v3-turbo')"
```

### Microphone permission not granted (macOS)
Open System Settings → Privacy & Security → Microphone and enable JARVIS.

### Accessibility tools not working (macOS)
Open System Settings → Privacy & Security → Accessibility, click +, and add `dist/JARVIS.app`.
