# =============================================================================
# setup_rvc_win.ps1  —  JARVIS 윈도우 RVC 음성 런타임 설치
# =============================================================================
# !! WINDOWS ONLY — 맥/리눅스에서 실행하지 말 것 !!
#
# 이 스크립트가 하는 일:
#   1. Python 3.10+ 가상환경(.venv-rvc-win) 생성
#   2. PyTorch (CPU 기본, CUDA 선택 가능) 설치
#   3. rvc-python을 fairseq 없이 설치
#   4. transformers + huggingface_hub (fairseq-free contentvec 로더용)
#   5. edge-tts, faster-whisper, soundfile 설치
#   6. contentvec·rmvpe 공개 자산 HuggingFace에서 다운로드
#
# ⚠️  fairseq-free 패치 안내 (WINDOWS-VERIFY-REQUIRED):
#   rvc-python의 hubert 로딩 두 곳을 transformers로 교체해야 한다:
#     - rvc_python/modules/vc/utils.py  : load_hubert()
#     - rvc_python/lib/jit/get_hubert.py : 내부 로딩 로직
#   jarvis/vc/win/hubert_transformers.py 의 load_hubert_transformers() 를
#   위 두 곳에 monkey-patch하거나 직접 교체하라.
#   실제 변환 음질은 윈도우 실기기에서 확인해야 함.
#
# 사전 요구사항:
#   - Python 3.10 이상 (python.exe가 PATH에 있어야 함)
#   - PowerShell 5.1+ 또는 PowerShell Core 7+
#   - 인터넷 연결 (HuggingFace 다운로드용)
#   - jarvis.pth + jarvis.index 는 별도 경로에 배치 (아래 $JarvisModelDir 참고)
#
# 실행:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
#   .\setup_rvc_win.ps1
#   또는 CUDA GPU 있으면:
#   .\setup_rvc_win.ps1 -UseCuda
# =============================================================================

param(
    [switch]$UseCuda,          # GPU (CUDA 12.1) PyTorch 설치
    [string]$PythonExe = "python",  # python 실행 파일 경로
    [string]$AssetDir = "$env:USERPROFILE\.jarvis\rvc_assets",  # 자산 캐시 폴더
    [string]$JarvisModelDir = "C:\jarvis\voice_models"  # jarvis.pth / jarvis.index 위치
)

$ErrorActionPreference = "Stop"
$VenvDir = ".venv-rvc-win"

Write-Host "=== JARVIS Windows RVC 런타임 설치 ===" -ForegroundColor Cyan
Write-Host "Python: $PythonExe | CUDA: $UseCuda | AssetDir: $AssetDir"

# -----------------------------------------------------------------------------
# 1. 가상환경 생성
# -----------------------------------------------------------------------------
if (-not (Test-Path "$VenvDir\Scripts\python.exe")) {
    Write-Host "`n[1/6] 가상환경 생성: $VenvDir" -ForegroundColor Yellow
    & $PythonExe -m venv $VenvDir
} else {
    Write-Host "`n[1/6] 가상환경 이미 존재: $VenvDir" -ForegroundColor Green
}

$pip = "$VenvDir\Scripts\pip.exe"
$python = "$VenvDir\Scripts\python.exe"

# pip 업그레이드
& $pip install --upgrade pip --quiet

# -----------------------------------------------------------------------------
# 2. PyTorch 설치 (CPU 기본 / CUDA 선택)
# -----------------------------------------------------------------------------
Write-Host "`n[2/6] PyTorch 설치..." -ForegroundColor Yellow
if ($UseCuda) {
    # CUDA 12.1 (최신 안정; CUDA 버전은 nvidia-smi로 확인 후 조정)
    & $pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
} else {
    # CPU only — 설치 크기 작음, 추론 속도 느릴 수 있음
    & $pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
}

# -----------------------------------------------------------------------------
# 3. rvc-python — fairseq 없이 설치
#    방법: 의존성 없이 설치 후 필수 패키지만 따로 설치 (fairseq 제외)
# -----------------------------------------------------------------------------
Write-Host "`n[3/6] rvc-python 설치 (fairseq 제외)..." -ForegroundColor Yellow

# rvc-python을 --no-deps로 먼저 받고, 필요한 의존성을 수동 설치
# (fairseq==0.12.2 는 의도적으로 제외)
& $pip install rvc-python --no-deps

# rvc-python 실제 의존성 (fairseq 제외):
& $pip install `
    numpy `
    scipy `
    librosa `
    "faiss-cpu>=1.7.2" `
    "praat-parselmouth>=0.4.2" `
    "pyworld>=0.3.2" `
    torchcrepe `
    "onnxruntime>=1.14" `
    noisereduce

# ⚠️ 참고: rvc-python 버전 업 시 pip show rvc-python 로 의존성 재확인할 것.
# fairseq를 의도적으로 제외했으므로 rvc_python.modules.vc.utils.load_hubert()
# 가 import 실패할 수 있다 → 아래 패치 단계 필수.

# -----------------------------------------------------------------------------
# 4. transformers + huggingface_hub (fairseq-free contentvec 로더)
# -----------------------------------------------------------------------------
Write-Host "`n[4/6] transformers + huggingface_hub 설치..." -ForegroundColor Yellow
& $pip install "transformers>=4.36" "huggingface_hub>=0.20" "safetensors>=0.4"

# -----------------------------------------------------------------------------
# 5. 보조 패키지: edge-tts, faster-whisper, soundfile
# -----------------------------------------------------------------------------
Write-Host "`n[5/6] edge-tts, faster-whisper, soundfile 설치..." -ForegroundColor Yellow
& $pip install "edge-tts>=6.1" "faster-whisper>=1.0" "soundfile>=0.12"

# -----------------------------------------------------------------------------
# 6. 공개 자산 다운로드 (contentvec · rmvpe)
#    jarvis.pth / jarvis.index 는 앱 동봉 — 여기서 받지 않음
# -----------------------------------------------------------------------------
Write-Host "`n[6/6] 공개 자산 다운로드 (contentvec · rmvpe)..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $AssetDir | Out-Null

$downloadScript = @"
import sys, shutil
from pathlib import Path

asset_dir = Path(r'$AssetDir')
asset_dir.mkdir(parents=True, exist_ok=True)

assets = [
    ('content-vec-best.safetensors', 'lengyue233/content-vec-best', 'pytorch_model.bin'),
    ('rmvpe.pt', 'lj1995/VoiceConversionWebUI', 'rmvpe.pt'),
]

try:
    from huggingface_hub import hf_hub_download
except ImportError:
    print('ERROR: huggingface_hub 미설치 — pip install huggingface_hub 실행 후 재시도')
    sys.exit(1)

for local_name, repo_id, repo_file in assets:
    target = asset_dir / local_name
    if target.exists():
        print(f'[캐시] {local_name} 이미 존재')
        continue
    print(f'[다운로드] {repo_id}/{repo_file} -> {target}')
    src = hf_hub_download(repo_id=repo_id, filename=repo_file)
    shutil.copy(src, target)
    print(f'[완료] {local_name}')

print(f'자산 폴더: {asset_dir}')
"@

& $python -c $downloadScript

# -----------------------------------------------------------------------------
# 완료 메시지 + 다음 단계 안내
# -----------------------------------------------------------------------------
Write-Host "`n=== 설치 완료 ===" -ForegroundColor Green
Write-Host @"

다음 단계 (WINDOWS-VERIFY-REQUIRED):

1. jarvis.pth + jarvis.index 를 아래 경로에 복사:
   $JarvisModelDir\jarvis.pth
   $JarvisModelDir\jarvis.index

2. fairseq-free hubert 패치 적용:
   rvc_python\modules\vc\utils.py 의 load_hubert() 를
   jarvis\vc\win\hubert_transformers.load_hubert_transformers() 로 교체.
   (또는 monkey-patch 스크립트 사용)
   ⚠️ 패치 후 실제 변환 음질을 윈도우에서 반드시 확인할 것.

3. 테스트 변환 (음질 확인):
   $VenvDir\Scripts\python.exe -c "
   from jarvis.vc.win.hubert_transformers import load_hubert_transformers
   h = load_hubert_transformers()
   print('로더 구조 OK:', h)
   "

4. 전체 음성 루프 확인:
   edge-tts(en-GB-RyanNeural) → RVC(jarvis.pth) → 재생
   f0_up=0, index_rate=0.9 권장 (스펙 § 결정 2 참고)

5. 문제 시 폴백:
   fairseq 설치(VS Build Tools + Python 3.10 필요):
   pip install fairseq==0.12.2
   docs\WINDOWS_VOICE.md 의 '폴백' 섹션 참고.

자세한 안내: docs\WINDOWS_VOICE.md
"@
