# 설계: 윈도우 크로스플랫폼 음성 (자비스 음색 유지)

날짜: 2026-06-12
상태: 사용자 승인됨 — 5개 항목 하나씩 확정
원칙: **맥은 현재 그대로 무손상**, 윈도우만 새 경로. 음질은 같은 모델이라 보존.

## 확정된 5개 결정

1. **RVC 추론(윈도우)**: rvc-python 파이프라인 유지하되 hubert/contentvec 로딩을
   **fairseq 제거 → transformers(`lengyue233/content-vec-best`)** 로 교체. 윈도우
   설치 깔끔(파이썬 버전·빌드도구 제약 제거). **맥은 현 fairseq 경로 유지.**
2. **베이스 TTS(윈도우)**: **edge-tts `en-GB-RyanNeural`(영어 남성)** → RVC(jarvis.pth).
   `f0_up=0`(Ryan이 이미 자비스 음역 ~108Hz라 무변조), `index_rate=0.9`. 맥에서
   edge→RVC 변환 라이브 검증 완료.
3. **플랫폼 분기**: `jarvis/core/platform_defaults.py`의 `apply_platform_defaults
   (settings)` — 윈도우면 `tts_backend="edge"`, `vc_backend="rvc"`, `rvc_f0_up=0`,
   `stt_backend="faster"`로 덮어씀. 맥이면 손 안 댐. env 명시값이 최우선. __main__이
   Settings 생성 직후 1회 호출.
4. **자산 배포**: jarvis.pth+index(~171MB, 자비스 정체성) **앱 동봉**. contentvec+
   rmvpe(공개) **첫 실행 HF 다운로드**(캐시). edge-tts 다운로드 없음.
5. **STT(윈도우)**: **faster-whisper**(CTranslate2) 백엔드. 같은 모델
   (large-v3-turbo)이라 인식 품질 동일. 윈도우=faster, **맥=mlx 유지**.

## 컴포넌트 (빌드 단위)

### A. `jarvis/stt/faster_whisper_stt.py` + factory
- `FasterWhisperSTT(repo, language="ko")` — STT 프로토콜(`warm`, `transcribe(pcm,
  sample_rate=16000, language=_UNSET)->str`). MLXWhisperSTT의 `_UNSET` 센티넬·언어
  자동감지(None 보존) 그대로 미러. faster-whisper `WhisperModel.transcribe(audio,
  language=...)`. 16k float32 입력.
- `jarvis/stt/factory.py` `make_stt(settings)`: `stt_backend`("mlx"|"faster")로
  분기. 기본 "mlx"(맥). __main__이 직접 생성 대신 factory 사용.
- config: `stt_backend: str = "mlx"`, `faster_whisper_compute: str = "int8"`(CPU 기본).
- 주입형(모델 로더 주입)으로 단위테스트(실제 추론 없이).

### B. `jarvis/core/platform_defaults.py`
- `apply_platform_defaults(settings, system=None)`: `system or sys.platform`이
  "win32"이면 음성 4종 설정 덮어씀(단, env로 명시된 건 안 덮음 — Settings는
  pydantic이라 env 우선 판단은 "기본값과 같으면 덮어쓴다"로). 맥/리눅스는 무변경.
- 순수 함수, 완전 단위테스트(system 주입).

### C. fairseq-free contentvec 로더 (윈도우 RVC 런타임)
- 윈도우 `.venv-rvc`는 fairseq 없이 구성. rvc-python의 hubert 로딩 두 곳
  (`modules/vc/utils.py`, `lib/jit/get_hubert.py`)을 transformers HubertModel
  (`lengyue233/content-vec-best`)로 대체하는 **패치/어댑터**. 출력 임베딩 차원·계약은
  fairseq 경로와 동일해야 jarvis.pth와 호환.
- 형식은 `voice_training/win/` 아래 패치 + 설치 스크립트. 코드 구조 단위테스트,
  **실제 변환 음질 검증은 윈도우에서**(맥은 fairseq 경로라 직접 비교만 참고).

### D. 윈도우 설치·자산
- `voice_training/setup_rvc_win.ps1`(또는 .bat): Python 3.10+ venv,
  torch(CPU/CUDA), rvc-python(fairseq 미설치) + transformers, contentvec·rmvpe HF
  다운로드. jarvis.pth/index는 앱 동봉 경로 참조.
- 자산 다운로드 헬퍼(공통): contentvec/rmvpe가 없으면 HF에서 받아 캐시.

## 비범위
- 컴퓨터 제어(pyautogui), 다른 OS 도구 포팅 — 별도(다음 단계).
- 실제 윈도우 머신 검증 — 사용자가 윈도우에서 실행 시.

## 검증
- 단위(여기): faster-whisper 백엔드(가짜 모델), make_stt 분기, platform_defaults
  (win/mac/linux), fairseq-free 로더 구조.
- 라이브(맥, 가능 범위): edge→RVC 이미 검증됨. faster-whisper 실제 1회 전사.
- 라이브(윈도우, 사용자): 전체 음성 루프(듣기+자비스 음색 말하기).
