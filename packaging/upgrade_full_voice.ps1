# upgrade_full_voice.ps1 — 배포 번들을 '개인용 풀음성'으로 업그레이드(Windows).
#
# 배포 JARVIS(.exe)는 기본 torch-free(edge-tts → ONNX RVC)다. 이 스크립트는 개인용과
# 동일한 음성 체인을 이 PC에 설치한다:
#   -Mode pocket (기본) : Kyutai Pocket TTS = 개인용 기본 음성(영어 자비스, 그대로).
#   -Mode rvc          : edge → torch-RVC(자비스 음색). fairseq-free(transformers hubert)
#                        — ⚠ WINDOWS-VERIFY-REQUIRED (setup_rvc_win.ps1 패치 절차 참고).
#
# 설치 후 %USERPROFILE%\.jarvis\voice_full.json 마커를 남기면, 다음 실행부터 launcher가
# edge/onnx 대신 이 체인을 켠다(jarvis/core/voice_full.py). torch 설치는 전적으로
# 이 PC에서, 사용자가 이걸 실행할 때만 일어난다.
#
#   powershell -ExecutionPolicy Bypass -File upgrade_full_voice.ps1 [-Mode pocket|rvc] [-Bundle <dir>]
param(
    [ValidateSet("pocket", "rvc")] [string]$Mode = "pocket",
    [string]$Bundle = $env:JARVIS_BUNDLE_ROOT,
    [string]$PythonExe = "python"
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$SelfDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $Bundle) { $Bundle = $SelfDir }

function Find-Dir([string[]]$cands) {
    foreach ($c in $cands) { if (Test-Path $c) { return (Resolve-Path $c).Path } }
    return $null
}
$SrcBundle = Find-Dir @("$Bundle\voice_full_src", "$SelfDir\..\voice_full_src", "$SelfDir\..")
$Assets    = Find-Dir @("$Bundle\voice_full_assets", "$SelfDir\..\voice_models")
if (-not $SrcBundle -or -not (Test-Path "$SrcBundle\jarvis")) {
    Write-Error "jarvis 소스 트리를 못 찾음(번들 손상?)"; exit 1
}
if (-not $Assets) { Write-Error "음성 모델 자산 디렉토리를 못 찾음"; exit 1 }

$Base    = Join-Path $env:USERPROFILE ".jarvis\voice-full"
$Src     = Join-Path $Base "src"
$Models  = Join-Path $Base "models"
$Marker  = Join-Path $env:USERPROFILE ".jarvis\voice_full.json"
New-Item -ItemType Directory -Force -Path $Src, $Models | Out-Null

Write-Host "==> 풀음성 업그레이드 (mode=$Mode)"
Write-Host "    bundle=$Bundle  base=$Base"

# 워커가 import할 jarvis 소스 배치
Write-Host "==> jarvis 소스 복사 -> $Src"
if (Test-Path "$Src\jarvis") { Remove-Item -Recurse -Force "$Src\jarvis" }
Copy-Item -Recurse "$SrcBundle\jarvis" "$Src\jarvis"

function Inject-Pth([string]$venv) {
    $py = Join-Path $venv "Scripts\python.exe"
    $sp = & $py -c "import site; print(site.getsitepackages()[0])"
    Set-Content -Path (Join-Path $sp "_jarvis_src.pth") -Value $Src -Encoding ASCII
    Write-Host "    .pth -> $sp\_jarvis_src.pth"
}

# 마커 작성: <pybin> <mode> KEY=VAL ...
function Write-Marker([string]$pybin, [string]$mode, [string[]]$kv) {
    $code = @'
import json, sys
mode, marker = sys.argv[1], sys.argv[2]
env = dict(p.split("=", 1) for p in sys.argv[3:])
verify = [v for k, v in env.items() if k.endswith("_PYTHON") or k.endswith("_MODEL_PATH")]
json.dump({"version": 1, "mode": mode, "env": env, "verify_paths": verify},
          open(marker, "w"), ensure_ascii=False, indent=2)
print("==> 마커 작성:", marker)
'@
    & $pybin -c $code $mode $Marker @kv
}

if ($Mode -eq "pocket") {
    $Venv = Join-Path $Base "venv-pocket"
    $HfCache = Join-Path $Base "hf-cache"
    $py   = Join-Path $Venv "Scripts\python.exe"
    $pip  = Join-Path $Venv "Scripts\pip.exe"
    Write-Host "==> Pocket venv 생성 -> $Venv"
    if (-not (Test-Path $py)) { & $PythonExe -m venv $Venv }
    & $pip install -U pip wheel | Out-Null
    Write-Host "==> pocket-tts + 런타임 의존성 설치(torch 포함 — 수백 MB)"
    & $pip install pocket-tts numpy soundfile

    # 음색 가중치(CC-BY-4.0): 토큰 없이 우리 릴리스에서 받아 HF 캐시에 배치. 오프라인
    # 플래그는 Pocket 워커에만 스코프(JARVIS_POCKET_HF_HOME) — 전역이면 Whisper STT가 막힌다.
    $WeightsUrl = if ($env:JARVIS_POCKET_WEIGHTS_URL) { $env:JARVIS_POCKET_WEIGHTS_URL } `
        else { "https://github.com/juzsojjang-ux/jarvis/releases/download/voice-weights/pocket-voice-weights.tar.gz" }
    if (-not (Test-Path (Join-Path $HfCache "hub\models--kyutai--pocket-tts"))) {
        Write-Host "==> 음색 가중치 내려받기(=167MB) -> $HfCache"
        New-Item -ItemType Directory -Force -Path $HfCache | Out-Null
        $Tarb = Join-Path $Base "pocket-weights.tar.gz"
        Invoke-WebRequest -Uri $WeightsUrl -OutFile $Tarb
        # Windows 10+ 의 bsdtar(tar.exe)가 .tar.gz 를 풀 수 있다.
        & tar -xzf $Tarb -C $HfCache
        Remove-Item -Force $Tarb
    } else {
        Write-Host "==> 음색 가중치 이미 있음 — 건너뜀"
    }

    Copy-Item -Force "$Assets\jarvis_en_ref.wav" "$Models\jarvis_en_ref.wav"
    Inject-Pth $Venv
    Write-Marker $py "pocket" @(
        "JARVIS_TTS_BACKEND=pocket",
        "JARVIS_VC_BACKEND=null",
        "JARVIS_REPLY_LANGUAGE=en",
        "JARVIS_POCKET_PYTHON=$py",
        "JARVIS_POCKET_REF_PATH=$Models\jarvis_en_ref.wav",
        "JARVIS_POCKET_HF_HOME=$HfCache"
    )
    Write-Host ""
    Write-Host "==> Pocket 음성 설치 완료 - HF 토큰 불필요. JARVIS를 재시작하세요."
    Write-Host "    음색 모델: Kyutai pocket-tts (CC-BY-4.0)"
}
elseif ($Mode -eq "rvc") {
    # edge → torch-RVC(자비스 음색). fairseq-free(transformers hubert). ⚠ 검증 필요.
    $Venv = Join-Path $Base "venv-rvc"
    $py   = Join-Path $Venv "Scripts\python.exe"
    $pip  = Join-Path $Venv "Scripts\pip.exe"
    Write-Host "==> RVC venv 생성 -> $Venv (torch/transformers, 수 분 소요)"
    if (-not (Test-Path $py)) { & $PythonExe -m venv $Venv }
    & $pip install -U pip wheel setuptools | Out-Null
    & $pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
    & $pip install rvc-python --no-deps
    & $pip install numpy scipy librosa soundfile faiss-cpu torchcrepe pyworld av loguru tqdm audioread resampy
    & $pip install "transformers>=4.36" "huggingface_hub>=0.20" "safetensors>=0.4"
    Copy-Item -Force "$Assets\jarvis.pth" "$Models\jarvis.pth"
    if (Test-Path "$Assets\jarvis.index") { Copy-Item -Force "$Assets\jarvis.index" "$Models\jarvis.index" }
    Inject-Pth $Venv
    Write-Marker $py "rvc" @(
        "JARVIS_TTS_BACKEND=edge",
        "JARVIS_VC_BACKEND=rvc",
        "JARVIS_RVC_PYTHON=$py",
        "JARVIS_RVC_MODEL_PATH=$Models\jarvis.pth",
        "JARVIS_RVC_INDEX_PATH=$Models\jarvis.index",
        "JARVIS_RVC_F0_UP=0"
    )
    Write-Host "==> RVC 음색 설치 완료. ⚠ fairseq-free hubert 패치는 setup_rvc_win.ps1 안내를 따르세요."
}

Write-Host "==> 완료. JARVIS를 재시작하세요."
