# JARVIS — 이어서 작업하기 (핸드오프 노트)

> 다른 세션/데스크톱 앱에서 이어서 작업할 때 이 파일 + 자동 메모리(`project_jarvis.md`)면
> 컨텍스트가 그대로 복원됩니다. "자비스 이어서 하자"로 시작하세요.

**작성 시점:** 2026-06-10 · **브랜치:** `phase2-jarvis-voice-dropin` (main 미머지)
**상태:** 전체 테스트 green, ruff clean. 같은 맥이면 venv·모델 그대로라 바로 실행됨.

---

## 한 줄 요약
이성재 개인용 한국어 음성비서 JARVIS. 푸시투토크 → 로컬 STT(mlx-whisper) → **두뇌(Claude 구독
로그인, API 키 없음)** → **자비스 음성(XTTS 제로샷 클로닝)** → 재생 + **화면 HUD 오버레이**.

## 이번 작업에서 완성한 것 (사용자 지시 3+1건)
1. **두뇌 = Claude 구독 로그인** (API 과금 회피). `claude-agent-sdk`가 로그인된 Pro/Max로 추론.
   - `jarvis/brain/subscription.py`(`SubscriptionBrain`) + `factory.py`. 기본 `brain_backend="subscription"`.
   - 격리: 자식 env에서 `ANTHROPIC_API_KEY` 제거 + `setting_sources=[]` + `allowed_tools=[]` + `max_turns=1`.
2. **자비스 음성** (GPU 학습 없이, 사용자 제공 클립으로 즉시). **XTTS v2**(`.venv-xtts`, py3.11).
   - 참조: `voice_models/jarvis_ref.wav` = 다운로드폴더 `J.A.R.V.I.S.` ProffieOS 보이스팩의
     **무압축 44.1k WAV**(`boot.wav` 16초 등)로 만든 26초 HQ 참조.
   - `jarvis/tts/xtts_worker.py`(latent 캐시 + temp0.6/rep5/split + 꼬리트림·정규화) + `xtts_kr.py`.
   - `tts_backend="auto"`: `.venv-xtts` + 참조 있으면 xtts, 없으면 macOS `say`.
3. **HUD 오버레이** (어벤져스 자비스 원형 인터페이스, Chrome 아님). `jarvis/hud/`.
   - `orb_server.py`(stdlib SSE) + `orb.html`(Canvas2D, 투명·오프라인) + `overlay_mac.py`(pyobjc 투명
     클릭통과 항상위 WKWebView, 별도 프로세스). 말할 때만 화면에 떠오름.
4. (보너스) **RVC 드롭인 경로** 유지: `voice_models/jarvis.pth`(학습본) 넣으면 `vc_backend="auto"`로
   자동 전환. 런타임 `.venv-rvc`(py3.10) 설치됨. `jarvis/vc/resolve.py`·`rvc_infer_cli.py`.

## 실행
```bash
cd ~/jarvis
python -m jarvis            # 우측 옵션키 누른 채 한국어로 말하기, 말하면 화면에 HUD
```
사전: ① macOS 마이크/손쉬운사용 권한 ② 키체인은 구독 두뇌에선 불필요(API 백엔드만 필요).

## 격리 venv (같은 맥엔 이미 다 있음 / 다른 맥은 재설치)
- `.venv` 메인(py3.11) · `.venv-tts` MeloTTS · `.venv-xtts` XTTS · `.venv-rvc` RVC(py3.10)
- 재설치: `voice_training/setup_xtts.sh` (자비스 음성), `setup_rvc.sh` (RVC 경로)

## 검증
```bash
.venv/bin/python -m pytest -q      # 전체 green
.venv/bin/python -m ruff check .   # clean
```

## 열린 항목 / 다음 후보
- [ ] **음질 추가 튜닝**: 사용자 v3a/v3b/HQ 중 선호 확정 시 파라미터 고정. 더 깨끗한 참조가 최대 레버.
- [ ] **구독 두뇌에 도구 연결**: 현재 대화형만. 날씨/기억/voice_status를 SDK 커스텀툴(MCP)로 붙이기.
- [ ] **XTTS 지연**: CPU 합성 문장당 수 초. `JARVIS_XTTS_DEVICE=mps`로 가속(가끔 불안정) 검토.
- [ ] main 머지 여부 결정 (`superpowers:finishing-a-development-branch`).
- [ ] (원하면) 맥 `.app` 패키징 — 터미널 없이 더블클릭 실행.

## 경계 (유지)
- 저작권 자비스 음원을 **내가 자동 다운로드하지 않음**. 사용자가 제공한 클립만 사용(개인·로컬·비배포).
- Colab GPU 학습은 사용자 계정 영역. premiere-pro MCP 실연결은 사용자가 보류시킴.

## 핵심 함정 (재현됨)
- transformers **5.x 불가**(`isin_mps_friendly` 제거) → XTTS는 `transformers>=4.40,<5`.
- torch≥2.9는 `torchcodec` 필요(`coqui-tts[codec]`).
- RVC: numba0.56.4/numpy1.23.5는 **py3.10 전용** → `.venv-rvc`만 3.10, fairseq은 One-sixth 포크.
- HUD 오버레이는 venv 파이썬 프로세스라 computer-use 스크린샷엔 안 잡힘(실제 화면엔 뜸).
