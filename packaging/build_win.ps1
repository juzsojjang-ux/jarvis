# build/build_win.ps1 — Windows build script for JARVIS lightweight-core distributable.
#
# REQUIREMENTS
# ============
#   • Windows 10/11 (x64)
#   • Python 3.11 installed (python3.11 on PATH, or adjust $PythonExe below)
#   • JARVIS main venv at .venv  (create: python -m venv .venv; .venv\Scripts\pip install -e .[dev])
#   • Run from the repo root:  .\build\build_win.ps1
#
# NOTE: The claude-agent-sdk bundled CLI is a macOS arm64 Mach-O binary.
#       It CANNOT run on Windows.  The subscription brain requires the claude CLI
#       to be installed separately on Windows — see docs/PACKAGING.md.
#       The spec detects this at build time and skips the bundle if the binary
#       is not a Windows executable.
#
# OUTPUT
#   dist\JARVIS\JARVIS.exe    — onedir bundle (no separate .app on Windows)
#
# SIGNING — SmartScreen
# =====================
#   Without an EV (Extended Validation) code-signing certificate, Windows
#   SmartScreen will flag JARVIS.exe as an untrusted app.  EV certs cost
#   ~$300-600/yr from DigiCert, Sectigo, etc.  OV (standard) certs exist but
#   SmartScreen reputation takes months to build; EV gets instant trust.
#
#   Once you have the cert (.pfx):
#       signtool sign /fd SHA256 /p12 cert.pfx /p <password> `
#           /tr http://timestamp.sectigo.com /td SHA256 `
#           dist\JARVIS\JARVIS.exe
#
#   Wrap in an installer (optional, recommended):
#       Use NSIS (free) or Inno Setup (free) to produce a signed .exe installer,
#       or WiX for an .msi.  Sign the installer too.
#
# WITHOUT SIGNING
# ===============
#   Users can bypass SmartScreen by clicking "More info → Run anyway".
#   For internal/developer distribution this is acceptable.
#

param(
    [switch]$Verbose
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Venv      = Join-Path $RepoRoot ".venv"
$Pip       = Join-Path $Venv "Scripts\pip.exe"
$PyInstaller = Join-Path $Venv "Scripts\pyinstaller.exe"
$Spec      = Join-Path $PSScriptRoot "jarvis.spec"

Write-Host "=========================================="
Write-Host "  JARVIS Windows Build"
Write-Host "  Repo:  $RepoRoot"
Write-Host "  Venv:  $Venv"
Write-Host "=========================================="

# --- Sanity checks -----------------------------------------------------------
if (-not (Test-Path "$Venv\Scripts\python.exe")) {
    Write-Error @"
Venv not found at $Venv
Create it:
  python -m venv .venv
  .venv\Scripts\pip install -e ".[dev]"
"@
    exit 1
}

if ($env:OS -ne "Windows_NT") {
    Write-Error "This script is Windows-only. Use build_mac.sh on macOS."
    exit 1
}

# --- Install / upgrade PyInstaller -------------------------------------------
Write-Host ""
Write-Host "[1/3] Installing/upgrading PyInstaller..."
& $Pip install --quiet --upgrade "pyinstaller>=6.0"
$PyIVersion = & $PyInstaller --version 2>&1
Write-Host "      PyInstaller: $PyIVersion"

# --- Run PyInstaller ---------------------------------------------------------
Write-Host ""
Write-Host "[2/3] Running PyInstaller..."
Set-Location $RepoRoot
& $PyInstaller $Spec --noconfirm
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

# --- Report results ----------------------------------------------------------
Write-Host ""
Write-Host "[3/3] Build complete."

$OnedirExe = Join-Path $RepoRoot "dist\JARVIS\JARVIS.exe"
if (Test-Path $OnedirExe) {
    $Size = (Get-Item $OnedirExe).Length / 1MB
    Write-Host ""
    Write-Host ("  Executable: $OnedirExe  ({0:F0} MB)" -f $Size)
    Write-Host ""
    Write-Host "  Quick test (will attempt to start JARVIS — Ctrl+C after a few seconds):"
    Write-Host "    $OnedirExe"
}

Write-Host ""
Write-Host "SIGNING REMINDER"
Write-Host "  The built EXE is unsigned.  Windows SmartScreen will flag it."
Write-Host "  Sign with an EV code-signing certificate before distribution."
Write-Host "  See docs\PACKAGING.md for the full signing workflow."
Write-Host ""
