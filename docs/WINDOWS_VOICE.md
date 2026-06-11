# JARVIS 윈도우 음성 경로 (Windows Voice Path)

> **대원칙**: 맥 경로(.venv-rvc, fairseq, mlx-whisper)는 절대 건드리지 않는다.
> 윈도우 전용 경로만 이 문서가 다룬다.

## 개요 (Architecture)

| 컴포넌트 | 맥 (현재) | 윈도우 (이 문서) |
|---------|----------|----------------|
| STT | mlx-whisper (large-v3-turbo) | faster-whisper (large-v3-turbo) |
| TTS 베이스 | edge-tts en-GB-RyanNeural | edge-tts en-GB-RyanNeural |
| 음색 변환 | rvc-python + fairseq | rvc-python + **fairseq-free** (transformers) |
| 허버트 로더 | fairseq checkpoint_utils | **jarvis.vc.win.hubert_transformers** |
| 모델 | jarvis.pth + jarvis.index | 동일 (앱 동봉) |

음성 흐름: `STT(faster-whisper) → 브레인 → edge-tts → RVC(jarvis.pth) → 재생`

---

## 설치 방법

### 사전 요구사항

- Python 3.10 이상 (python.exe가 PATH에 있을 것)
- PowerShell 5.1+ 또는 PowerShell Core 7+
- 인터넷 연결 (HuggingFace 자산 다운로드)

### setup_rvc_win.ps1 실행

```powershell
# 실행 정책 허용 (최초 1회)
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

# 저장소 루트에서
cd C:\path\to\jarvis
.\voice_training\setup_rvc_win.ps1

# GPU(CUDA) 있으면
.\voice_training\setup_rvc_win.ps1 -UseCuda
```

스크립트가 하는 일:
1. `.venv-rvc-win` 가상환경 생성
2. PyTorch (CPU 또는 CUDA) 설치
3. rvc-python **fairseq 없이** 설치
4. transformers + huggingface_hub 설치 (fairseq-free 로더용)
5. edge-tts, faster-whisper, soundfile 설치
6. contentvec · rmvpe 공개 자산 HuggingFace에서 다운로드 (`~/.jarvis/rvc_assets/`)

---

## 자산 배치

### 공개 자산 (자동 다운로드)

| 파일 | 소스 | 캐시 위치 |
|------|------|----------|
| `content-vec-best.safetensors` | `lengyue233/content-vec-best` | `~/.jarvis/rvc_assets/` |
| `rmvpe.pt` | `lj1995/VoiceConversionWebUI` | `~/.jarvis/rvc_assets/` |

### 앱 동봉 자산 (수동 배치 필요)

`jarvis.pth`와 `jarvis.index`는 공개 HuggingFace에 없으므로 직접 복사해야 한다:

```
C:\jarvis\voice_models\
    jarvis.pth      ← 맥에서 복사 (171MB 이하)
    jarvis.index    ← 맥에서 복사
```

또는 `setup_rvc_win.ps1`의 `-JarvisModelDir` 파라미터로 경로 지정.

---

## fairseq-free 허버트 패치

rvc-python 0.1.5는 fairseq를 hubert/contentvec 로딩에만 사용한다:
- `rvc_python/modules/vc/utils.py` → `load_hubert()`
- `rvc_python/lib/jit/get_hubert.py` → 내부 로직

윈도우에서는 이 두 곳을 `jarvis.vc.win.hubert_transformers.load_hubert_transformers()`로 교체한다.

```python
# 예시: 실행 시작부에 monkey-patch (진입점에 추가)
from jarvis.vc.win.hubert_transformers import load_hubert_transformers
import rvc_python.modules.vc.utils as rvc_utils
rvc_utils.load_hubert = lambda *a, **kw: load_hubert_transformers()
```

> ⚠️ **WINDOWS-VERIFY-REQUIRED**: 패치 후 실제 변환 결과를 들어봐야 한다.
> 이론상 동일 가중치라 같은 임베딩이 나오지만, 레이어 인덱스와 투영 방식은
> 윈도우 실기기에서 fairseq 결과와 대조 후 확정할 것.

---

## VERIFY ON WINDOWS 체크리스트

> 아래 항목은 이 코드베이스만으로 완결되지 않는다.
> 윈도우 머신에서 직접 실행하고 확인해야 한다.

### 구조 확인 (Mac에서도 가능)

- [x] `tests/vc/test_assets.py` — 자산 다운로더 구조 (3 tests)
- [x] `tests/vc/test_hubert_transformers.py` — 로더 래퍼 구조 (5 tests)

### 윈도우 실기기 확인 (MUST DO ON WINDOWS)

- [ ] `setup_rvc_win.ps1` 실행 성공 (패키지 설치 오류 없음)
- [ ] `contentvec·rmvpe` 자산 정상 다운로드 및 캐시 확인
- [ ] fairseq-free 패치 적용 후 rvc-python import 오류 없음
- [ ] 테스트 변환: 짧은 WAV → RVC(jarvis.pth) → 출력 WAV 생성 확인
- [ ] 출력 음질 청취 확인 (자비스 음색 유지)
- [ ] edge-tts(en-GB-RyanNeural) → RVC 전체 파이프라인 실행
- [ ] faster-whisper 한국어 전사 확인
- [ ] `f0_up=0`, `index_rate=0.9` 파라미터로 음색 자연스러움 확인
- [ ] (선택) 맥 RVC 출력과 청각 비교

### f0_up 튜닝 지침

- 기본값 `f0_up=0` (Ryan 목소리가 이미 자비스 음역 ~108Hz라 변조 불필요)
- 목소리가 너무 낮으면: `f0_up=2` (반음 2개 업)
- 목소리가 너무 높으면: `f0_up=-2`
- `jarvis/core/platform_defaults.py`의 `rvc_f0_up` 설정에서 조정

---

## 폴백: fairseq 설치 방법 (선택)

fairseq-free 접근이 음질 문제를 일으킬 경우, fairseq를 윈도우에 직접 설치한다:

```powershell
# 요구사항: VS Build Tools 2019+ (C++ Build Tools), Python 3.10 권장
# Visual C++ Build Tools 다운로드: https://visualstudio.microsoft.com/visual-cpp-build-tools/

pip install fairseq==0.12.2
```

> 주의: fairseq는 Python 3.11+에서 빌드 실패할 수 있다. Python 3.10 venv 권장.
> VS Build Tools 설치 + `cl.exe` PATH 등록 필요.
> 이 경로를 택하면 monkey-patch 없이 rvc-python 기본 로딩이 그대로 작동한다.

---

## 관련 파일

| 파일 | 설명 |
|------|------|
| `jarvis/vc/assets.py` | 공개 자산 다운로더 (주입형, 테스트 가능) |
| `jarvis/vc/win/__init__.py` | 윈도우 vc 패키지 |
| `jarvis/vc/win/hubert_transformers.py` | fairseq-free contentvec 로더 |
| `voice_training/setup_rvc_win.ps1` | 윈도우 설치 스크립트 |
| `jarvis/core/platform_defaults.py` | 플랫폼별 설정 분기 |
| `jarvis/stt/faster_whisper_stt.py` | Windows STT 백엔드 |
| `tests/vc/test_assets.py` | 자산 다운로더 단위 테스트 |
| `tests/vc/test_hubert_transformers.py` | 로더 래퍼 단위 테스트 |
