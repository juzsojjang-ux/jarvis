#!/usr/bin/env bash
# build/build_mac.sh — macOS build script for JARVIS lightweight-core distributable.
#
# REQUIREMENTS
# ============
#   • macOS (Apple Silicon or Intel)
#   • JARVIS main venv at ../.venv  (python3.11, pip, pyinstaller)
#   • Run from the repo root OR from this build/ directory — the script is
#     path-independent.
#
# OUTPUT
#   dist/JARVIS/       — onedir bundle (for direct testing)
#   dist/JARVIS.app    — macOS .app bundle
#
# SIGNING (you must do this — we cannot do it for you)
# =====================================================
#   A working unsigned .app can be opened with right-click → Open on developer
#   Macs.  End-users on default Gatekeeper settings will see "damaged" errors
#   unless the app is signed AND notarized.
#
#   Step 1 — Enroll in Apple Developer Program ($99/yr):
#       https://developer.apple.com/programs/enroll/
#
#   Step 2 — Code-sign:
#       codesign --force --deep --sign "Developer ID Application: Your Name (TEAMID)" \
#           --entitlements build/entitlements.plist \
#           dist/JARVIS.app
#
#   Step 3 — Notarize (requires Xcode CLI + Apple ID app-specific password):
#       xcrun notarytool submit dist/JARVIS.zip \
#           --apple-id your@email.com \
#           --password <APP_SPECIFIC_PW> \
#           --team-id TEAMID \
#           --wait
#       xcrun stapler staple dist/JARVIS.app
#
#   Step 4 — Distribute (DMG recommended):
#       hdiutil create -volname JARVIS -srcfolder dist/JARVIS.app \
#           -ov -format UDZO dist/JARVIS.dmg
#
# WITHOUT SIGNING
# ===============
#   Testers can bypass Gatekeeper with:
#       xattr -dr com.apple.quarantine dist/JARVIS.app
#   or right-click → Open once.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV="$REPO_ROOT/.venv"
PIP="$VENV/bin/pip"
PYINSTALLER="$VENV/bin/pyinstaller"
SPEC="$SCRIPT_DIR/jarvis.spec"

echo "=========================================="
echo "  JARVIS macOS Build"
echo "  Repo: $REPO_ROOT"
echo "  Venv: $VENV"
echo "=========================================="

# --- Sanity checks -----------------------------------------------------------
if [[ ! -f "$VENV/bin/python" ]]; then
    echo "ERROR: venv not found at $VENV"
    echo "  Create it: python3.11 -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'"
    exit 1
fi

if [[ "$(uname)" != "Darwin" ]]; then
    echo "ERROR: This script is macOS-only. Use build_win.ps1 on Windows."
    exit 1
fi

# --- Install / upgrade PyInstaller in the venv -------------------------------
echo ""
echo "[1/3] Installing/upgrading PyInstaller..."
"$PIP" install --quiet --upgrade "pyinstaller>=6.0"
echo "      PyInstaller: $("$PYINSTALLER" --version)"

# --- Run PyInstaller ---------------------------------------------------------
echo ""
echo "[2/3] Running PyInstaller..."
cd "$REPO_ROOT"
"$PYINSTALLER" "$SPEC" --noconfirm

echo ""
echo "[3/3] Build complete."

# --- Report results ----------------------------------------------------------
ONEDIR="$REPO_ROOT/dist/JARVIS"
APP="$REPO_ROOT/dist/JARVIS.app"

if [[ -d "$APP" ]]; then
    APP_SIZE=$(du -sh "$APP" 2>/dev/null | cut -f1)
    echo ""
    echo "  .app bundle: $APP  ($APP_SIZE)"
    echo "  Binary:      $APP/Contents/MacOS/JARVIS"
    echo ""
    echo "  Quick test (will try to start JARVIS — Ctrl+C after a few seconds):"
    echo "    $APP/Contents/MacOS/JARVIS"
    echo ""
    echo "  Or via open:"
    echo "    open $APP"
fi

if [[ -d "$ONEDIR" ]]; then
    ONEDIR_SIZE=$(du -sh "$ONEDIR" 2>/dev/null | cut -f1)
    echo "  onedir:      $ONEDIR  ($ONEDIR_SIZE)"
fi

echo ""
echo "SIGNING REMINDER"
echo "  The built .app is unsigned.  End-users will see Gatekeeper errors."
echo "  Sign + notarize with an Apple Developer ID ($99/yr) before distribution."
echo "  See docs/PACKAGING.md for the full signing workflow."
echo ""
