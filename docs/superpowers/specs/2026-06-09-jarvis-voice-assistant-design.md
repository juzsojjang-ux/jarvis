# 자비스(JARVIS) 음성 비서 — 설계 스펙 (Phase 1 / v1)

- **작성일:** 2026-06-09
- **작성자:** 이성재 + Claude (brainstorming)
- **상태:** 설계 확정 대기 (사용자 검토 단계)
- **근거:** 7개 영역 병렬 리서치 + 영역별 적대적 검증 (워크플로 `jarvis-spec-research`, 14개 에이전트, 2026-06-09). 모든 라이브러리/버전/라이선스/애플실리콘 실현가능성은 웹 사실확인을 거침.

---

## 1. 한 줄 요약

> 맥(애플 실리콘)에서 도는 **개인용 음성 비서**. 버튼을 눌러 한국어로 말하면 → 로컬 STT로 받아적고 → **Claude API**가 답하거나 작업을 실행하고 → **"진짜 자비스 목소리"(클로닝)** 로 한국어 답을 읽어준다. "그냥 물어보기"부터 "작업 전체 실행"까지 **하나의 에이전트 루프**가 처리하며, 능력은 **도구(tool)와 MCP 서버를 붙이는 것만으로** 무한히 확장된다.

---

## 2. 목표 / 비목표

### 목표 (v1)
1. 푸시투토크(PTT) → 로컬 한국어 STT → Claude 에이전트 루프(스트리밍 + tool-use) → 자비스 음색 TTS → 스피커, **끝에서 끝까지 동작**.
2. 처음부터 **tool-use를 내장**해 "단순 대화"와 "작업 실행"이 같은 엔진에서 나오게 한다.
3. **메모리**(나·선호·지난 맥락)를 세션을 넘어 유지.
4. **스타터 도구 2~3개**(웹검색, 시간/날씨) + 확장 골격(도구 레지스트리 + MCP 슬롯).
5. **자비스 음성 학습 루트**: 대사 수집 → 전처리 → 학습 → 장착까지 스크립트화된 1회성 파이프라인.

### 비목표 (v1에서 안 함, 후속 Phase)
- 웨이크워드("자비스") 핸즈프리 호출 → **Phase 2**.
- 맥/앱 제어·`premiere-pro-mcp` 실연결·리코 파이프라인 자동화 → **Phase 2~3**.
- 오프라인(완전 무인터넷) 두뇌 → 명시적 비목표(§9.1 참조).
- 배포/상용화 → **영구 비목표**(개인용·비공개 한정, §8.6 저작권 참조).

---

## 3. 확정된 제품 결정 (사용자 합의 완료)

| 항목 | 결정 |
|---|---|
| 형태 | 음성 비서 (진짜 자비스) |
| 활성화 (v1) | **푸시투토크**(단축키 hold). 웨이크워드는 Phase 2 |
| 응답 언어 | **한국어** |
| 목소리 | **실제 자비스(폴 베타니) 음색을 클로닝**, 한국어 발음 |
| 음성 학습 루트 | **포함** (대사 자동 수집 → 학습 → 장착) |
| STT | 로컬(맥에서 추론) |
| TTS | 로컬(맥에서 추론) |
| 두뇌 | **Claude API** (`claude-opus-4-8` 기본) — 클라우드 |
| 런타임 | **Python** |
| 비용 정책 | 학습 등 1회성 무거운 작업은 빌린 GPU/Colab 허용. **매일 쓰는 추론은 맥 로컬** |

---

## 4. 핵심 원칙: 엔진은 하나, 능력은 붙여 나간다

Claude의 **tool-use 루프**가 단일 엔진이다.
- 도구가 **필요 없으면** → Claude가 그냥 한국어로 답한다 (= 단순 대화/Q&A).
- 도구가 **필요하면** → Claude가 도구를 호출해 실행한다 (= 작업 수행).

따라서 "더 많은 걸 하게" 만드는 것은 **재작성이 아니라 도구/MCP 서버 추가**다. STT·TTS·음색변환·도구는 전부 **교체 가능한 백엔드(Protocol)** 로 두어, 한 군데를 바꿔도 나머지가 안 깨지게 한다.

---

## 5. 아키텍처

### 5.1 런타임 파이프라인 (상태 기계)

```
IDLE ──(PTT 누름)──▶ CAPTURING ──(PTT 뗌)──▶ TRANSCRIBING ──▶ THINKING ──▶ SPEAKING ──▶ IDLE
  ▲                      │                                                      │
  └──────────────── barge-in(말 끊기): PTT 다시 누름 → 재생 abort + 스트림 취소 ─┘

🎙 마이크(sounddevice 16k mono)
   → [STT] mlx-whisper large-v3-turbo, language="ko"
   → [BRAIN] AsyncAnthropic.messages.stream (+ 도구 루프, 메모리)
        · 응답 토큰을 문장 단위로 잘라 흘려보냄(incremental)
   → [TTS] MeloTTS-KR(한국어 발음)  →  [VC] RVC(자비스 음색)  →  재생(ring-buffer)
```

### 5.2 모듈 레이아웃

```
jarvis/
  __main__.py            # 엔트리: (Phase1) launchd/venv 스크립트 / (Phase2) rumps 메뉴바 + asyncio 스레드
  core/
    orchestrator.py      # 상태 기계, 턴 수명주기, barge-in
    events.py            # 스레드<->루프 브리지 (dataclass 이벤트)
    config.py            # pydantic settings, 백엔드 선택, 한국어 프롬프트, 키체인 접근
  audio/
    capture.py           # sd.InputStream(16k mono) + PTT 게이트
    playback.py          # sd.OutputStream ring-buffer 플레이어 + abort()
    vad.py               # (옵션) Silero VAD(ONNX) — Phase2 엔드포인팅/웨이크
  activation/
    base.py              # Activator 프로토콜
    ptt.py               # pynput keyboard.Listener(Key.alt_r) — Phase1 기본
    wakeword.py          # openWakeWord / Porcupine — Phase2
  stt/
    base.py              # STTBackend 프로토콜: transcribe(pcm)->str
    mlx_whisper.py       # 기본 (mlx-whisper)
  brain/
    claude.py            # AsyncAnthropic 스트리밍 + 수동 tool-use 루프(게이팅)
    memory.py            # markdown/json 메모리 스토어
    persona.py           # 자비스 한국어 집사 시스템 프롬프트(캐시 프리픽스)
    sentence.py          # 한국어 문장 분할(빠른 정규식) → TTS 큐
  tts/
    base.py              # TTSBackend 프로토콜: synth(text)->pcm
    melotts_kr.py        # 한국어 발음 생성 (별도 venv/프로세스)
  vc/
    base.py              # VoiceConversion 프로토콜 (TTS 후단 음색 슬롯)
    rvc.py               # 자비스 RVC 음색 변환
  tools/
    registry.py          # @beta_tool 등록 + Claude tools=[...] 스키마 생성 + 디스패치
    mcp_client.py        # MCP 슬롯: stdio_client + ClientSession (premiere-pro-mcp 등)
    builtin/
      web_search.py      # 서버사이드 web_search 툴 dict
      time_weather.py    # 로컬 @beta_tool
voice_training/          # 1회성 학습 루트(별도, §8)
  fetch.py  separate.py  segment.py  clean.py  resample.py  train_colab.ipynb
docs/superpowers/specs/  # 이 문서
```

> **핵심 구조 결정:** MeloTTS(고정된 옛 torch/transformers 의존성)는 **별도 venv/프로세스**로 격리한다(§6.2). 즉 자비스는 **2-프로세스 구조**(메인 + TTS 워커)다.

---

## 6. 서브시스템 스펙

각 항목: **결정 / 구성요소(핀 버전) / 동작 / 애플실리콘·지연 / 위험·완화**. ⚠️는 적대적 검증이 잡아낸 함정.

### 6.1 STT — 음성 → 한국어 텍스트

- **결정:** **`mlx-whisper`** 엔진 + **`mlx-community/whisper-large-v3-turbo`**, `language="ko"`. 얇은 커스텀 파이프라인(PTT 키업 = 깔끔한 엔드포인트라 VAD 불필요).
- **구성요소(핀):**
  - `mlx-whisper==0.4.3` (+ `mlx`도 핀 — 빠르게 바뀜)
  - `sounddevice==0.5.5` (arm64 휠이 PortAudio 번들 — brew 불필요)
  - `pynput` (PTT 글로벌 핫키)
  - `numpy` (16kHz mono float32 버퍼)
  - 폴백: `pywhispercpp==1.5.0`(whisper.cpp Metal/CoreML, 스트리밍 partial 필요 시) / `faster-whisper==1.2.1`(빌드 불필요 CPU 폴백, **느림**)
- **동작:** 시작 시 모델 1회 로드(warm) → PTT hold 동안 16k mono 녹음 → 키업 시 `mlx_whisper.transcribe(buf, path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language="ko")`.
- **애플실리콘/지연:** mlx-whisper가 M-시리즈 최속(턴어라운드 ~0.5–1.2s, 3–8초 발화 기준, M4 24GB). large-v3-turbo는 ~1.5GB(fp16), 16GB M1에서 여유.
- ⚠️ **검증이 잡은 함정:**
  - **faster-whisper / 기본 RealtimeSTT는 맥에서 CPU 전용**(CTranslate2에 Metal 없음) → 5~7배 느림. **GPU 가속은 MLX/Metal(mlx-whisper) 또는 Metal+CoreML/ANE(whisper.cpp)에서만.** PyTorch-MPS `openai-whisper`는 버그 경로 — **사용 금지**.
  - **distil-whisper는 영어 전용** — 한국어 불가.
  - **첫 실행은 오프라인 아님**(가중치 ~1.6GB 다운로드). 캐시 후 `HF_HUB_OFFLINE=1`, 모델은 **시작 시 1회 로드해 warm 유지**(콜드 로드 수 초는 핫패스 금지).
  - **한국어 정확도:** 깨끗한 읽기음성 ~2% CER이지만 **실제 마이크 잡음/대화체는 ~11% CER**. 캡처단 denoise/AGC 추가, 정확도 부족 시 **Korean fine-tune(1회 GPU)** — 단 safetensors→MLX/ggml 포맷 변환 필요.
  - mlx-whisper는 **one-shot(스트리밍 partial 없음)** — PTT 최종전사엔 OK. partial 필요하면 whisper.cpp로 교체.
  - pynput 글로벌 핫키는 **macOS 손쉬운 사용(Accessibility) 권한** 필요, 마이크는 **Microphone(TCC) 권한** 필요 — **둘 다 조용히 실패**(예외 없음). 권한은 실행 바이너리(Terminal vs .app)별로 따로 부여.

### 6.2 베이스 한국어 TTS — 텍스트 → 한국어 음성(음색변환 전단)

- **결정:** **MeloTTS** (`myshell-ai/MeloTTS-Korean`, `language='KR'`, **MIT**). CPU 실시간. 이 단계는 **발음만** 책임지고 음색은 다음 RVC 단계가 입힌다.
- **구성요소(핀):**
  - MeloTTS (git clone + `pip install -e .`), `python -m unidic download`
  - `python-mecab-ko` (한국어 형태소; 휠이 mecab-ko + mecab-ko-dic 번들)
  - **Python 3.10/3.11** 권장, **자체 venv/프로세스로 격리**
- **동작:** `from melo.api import TTS; m = TTS(language='KR', device='cpu'); m.tts_to_file(text, spk['KR'], out, speed=1.0)`. 출력 **44.1kHz mono** → RVC 입력 레이트로 리샘플.
- ⚠️ **검증이 잡은 함정:**
  - **Kokoro / MLX-Audio는 한국어 없음** → 후보에서 제외. F5-TTS-MLX도 한국어 모델 없음 + 비스트리밍 → 제외.
  - **Piper "한국어 = 깨끗한 MIT"는 거짓.** 공식 piper-voices에 한국어 없음. 유일한 비공식 `neurlang/piper-onnx-kss-korean`은 **CC-BY-NC-SA(비상업)** + 음질 평범, 엔진도 이제 GPLv3. → 베이스로 부적합(저지연 폴백 후보로만, 라이선스/품질 단점 명시).
  - **XTTS-v2: 애플실리콘 MPS 무한 행(wontfix)** → `device='cpu'` 강제 + 느림. 실시간 경로 부적합. 쓰면 `coqui-tts==0.27.5` + **별도 `pip install torch`**(0.27.4부터 torch 미번들), `COQUI_TOS_AGREED=1`. 오프라인/배치 용도만.
  - **MeCab 설치 함정:** `brew install mecab`은 **일본어 빌드(잘못된 사전)** — 보통 불필요. 정답은 **깨끗한 venv에서 `pip install python-mecab-ko`**(휠이 한국어 사전 번들), **`mecab-python3` 동시설치 금지**(NoneType 'pos' 충돌, issues #119/#121/#299). 설치 직후 한국어 한 문장 합성 **스모크 테스트**로 검증.
  - 콜드스타트(torch+VITS+MeCab 초기화 수 초) → **시작 시 warm**.
  - **샘플레이트 정렬:** MeloTTS 44.1k → RVC 입력(40k/48k)로 `soxr`/`torchaudio` 리샘플(안 하면 피치/아티팩트).

### 6.3 자비스 음색 변환 — 한국어 발음 + 자비스 음색

- **결정 — 아키텍처 A:** **MeloTTS-KR(발음) → RVC v2(음색)**. 발음과 음색을 **분리**해 "영어 목소리가 한국어를 어색하게 말하는" 문제를 구조적으로 회피(RVC는 언어 무관, 음색만 리페인트).
- **학습 vs 추론:** **RVC 학습은 CUDA 필요** → **Colab/빌린 GPU에서 1회**(~150–300 epoch, batch ~40) → `.pth` + `added_*.index`를 맥으로 복사 → **추론은 맥 로컬**.
- **로컬 추론 엔진(우선순위 — 검증 반영):**
  1. **`lextoumbourou/mlx-rvc`** (`uv pip install mlx-rvc`; v1/v2 + 32/40/48k + RMVPE/Harvest) — 1순위 후보
  2. **PyTorch-MPS macOS 포크** (`NevilPatel01/RVC-WebUI-MacOS`, `qingbo1011/RVC-WebUI-MacOS`) — 검증된 폴백
  3. ⚠️ **`Acelogic/RVC-MLX`는 "실험적"으로 강등** — LICENSE 없음(all-rights-reserved), AI생성, NaN/parity 디버그 흔적, 벤치는 M3 Max 128GB. 의존 전 라이선스·품질 A/B 필수.
- ⚠️ **검증이 잡은 함정:**
  - RVC는 **prosody(억양/말투)를 전달하지 않음** — 출력은 **MeloTTS 억양 + 자비스 음색**. 자비스 특유의 차분한 톤까지 원하면 아키텍처 B(GPT-SoVITS)만 가능(단 발음 리스크).
  - MLX-RVC는 **file-to-file 배치(스트리밍 아님)** → A는 2단 체인이라 **RVC는 TTS 문장이 끝나야 시작** → 단어단위 스트리밍 어려움, **발화(문장) 단위 지연**으로 설계.
  - **faiss-cpu는 `>=1.7.2`** (1.7.0은 arm64 휠 없음/소스빌드 실패). 전제로 **`brew install swig`**.
  - **하드웨어 바닥:** MeloTTS + HuBERT/ContentVec + RMVPE + generator 동시 상주 → **~16GB+ RAM 권장**. 8GB는 스왑/저하 → **사용자 맥 사양(칩+RAM) 측정 게이트** 필요.
  - 깊은 남성 한국어 소스가 자비스로 더 깨끗하게 변환됨(여성 기본 소스 피함). f0는 **RMVPE** 사용, index/retrieval ratio 튜닝.
- **대안 — 아키텍처 B (폴백): GPT-SoVITS** (MIT, v4=48k, 한국어 v2+). 단일모델 few-shot(텍스트→자비스 음색). 리스크: 영어전용 자비스 데이터로 **한국어 교차합성 시 억양/오발음**, 맥은 **CPU 전용 추론(MPS 품질 저하 + 메모리 누수)**. → A가 어색하면 B로 전환.

### 6.4 두뇌 — Claude API 에이전트 루프

- **결정:** `AsyncAnthropic` + `client.messages.stream(...)`. 기본 모델 **`claude-opus-4-8`**. 하나의 **프롬프트 캐시된 자비스 시스템 프롬프트** 아래 두 경로:
  - **대화 경로**(단순 한국어 Q&A): **`claude-haiku-4-5`** *(또는 Opus 4.8 + thinking 비활성 + "최종 답만" 지시)*, 도구 없음. → **모델 분기는 사용자 설정으로 노출**(Opus를 조용히 다운그레이드 금지).
  - **작업 경로**(행동): `claude-opus-4-8` + `thinking={"type":"adaptive"}` + `output_config={"effort":"high"}` + 도구.
- **구성요소(핀):** `anthropic==0.107.1` (`pip install "anthropic[mcp]"`; mcp 익스트라는 Python≥3.10). 키는 **Keychain 저장**(env/plaintext 금지).
- **도구 루프:** **수동 스트리밍 루프 + 음성 확인 게이팅**(자동 tool runner 아님) — shell/AppleScript/파일삭제 등 **되돌릴 수 없는 맥 동작**은 실행 전 음성 확인. 안전한 도구만일 땐 `tool_runner`가 더 간단(폴백).
- **메모리:** **markdown/json 스토어**를 시작 시 로드해 캐시 프리픽스에 주입(단일 사용자엔 이게 최적, 사용자의 `MEMORY.md` 패턴과 동일). 세션 중 갱신은 `{"role":"system"}` 메시지(beta `mid-conversation-system-2026-04-07`)로 — 캐시 안 깨짐. 자기수정 메모리가 필요하면 메모리 툴 `memory_20250818`.
- **증분 TTS:** `stream.text_stream` 델타 → 한국어 문장 버퍼 → 문장/절 경계마다 TTS로 flush(첫 청크는 첫 쉼표/절에서 공격적으로). 정규식 분할(빠름), **`kss` 금지**(시작/호출 지연 — 오프라인 정리용만; 참고로 kss는 BSD-3).
- ⚠️ **검증이 잡은 함정:**
  - **Opus 4.8 thinking은 adaptive 전용.** `budget_tokens`/`temperature`/`top_p`/`top_k` → **400**. 행동 제어는 프롬프트+`effort`로.
  - **`effort`는 Haiku 4.5에서 400** — **Haiku 경로엔 `output_config.effort`를 절대 넣지 말 것.** effort는 Opus 4.5+/Sonnet 4.6에서만.
  - **음성 지연 함정 ①:** Opus 4.8 adaptive thinking은 기본 `display:"omitted"` → **첫 오디오 전 무음**. 대화 경로는 thinking 비활성/Haiku로.
  - **음성 지연 함정 ②:** thinking 비활성 시 Opus 4.8이 추론을 말로 흘릴 수 있음 → **"최종 발화 답만, 서론·추론 금지" 시스템 지시**.
  - **프롬프트 캐시:** Opus 4.8 최소 캐시 프리픽스 **4096 토큰** — 짧은 페르소나는 **조용히 캐시 안 됨**. 시작 시 `max_tokens=0`로 pre-warm(단, **스트리밍/thinking enabled/format/tool_choice any|tool과 함께 쓰면 거부** → 평범한 비스트리밍 요청). `usage.cache_read_input_tokens != 0` 확인. 타임스탬프/UUID는 프리픽스 뒤로.
  - **지연 현실:** Opus 4.8 TTFT는 비추론 ~1.6s+, 추론·도구 턴은 멀티초. 도구 N개 = **N번 순차 라운드트립**. 도구 턴엔 멀티초를 **하드 제약으로 가정**, 음성 필러("잠시만요") 재생.
  - 429/5xx는 SDK가 기본 재시도하지만 **음성 UX엔 스폰 필러 + 네트워크 손실 동작** 정의.

### 6.5 도구 레이어 + MCP 클라이언트 (확장 골격)

- **결정:** 앱이 **MCP 클라이언트(stdio)** 로 동작. **원격전용 mcp_servers 커넥터 아님.**
- **구성요소(핀):** `pip install "anthropic[mcp]"` + `mcp==1.27.x`.
  - 로컬 도구: `@beta_tool`/`@beta_async_tool` 함수(subprocess/`osascript`(AppleScript)/`pathlib`).
  - 웹검색: **서버사이드 `web_search_20260209`** 툴 dict(Anthropic 측 실행, $10/1k검색, **비로컬** — "완전 로컬"엔 위배, 필요 시 로컬 검색 툴로 교체).
  - MCP: `stdio_client(StdioServerParameters(command="node", args=[".../premiere-pro-mcp/dist/index.js"], env={"PREMIERE_TEMP_DIR": "..."}))` → `ClientSession.initialize()` → `list_tools()` → `anthropic.lib.tools.mcp.async_mcp_tool(tool, session)`로 래핑 → 하나의 `tools=[...]`에 병합.
- **레지스트리:** config 기반(JSON: `{name, command, args, env}` MCP 서버 목록 + 데코레이터 등록 로컬 함수). **"능력 추가" = `@beta_tool` 하나 추가 OR JSON 한 줄 추가** — 호출부 재작성 0.
- ⚠️ **검증이 잡은 함정:**
  - **`anthropic.lib.tools.mcp` 헬퍼는 소스엔 있으나 핀 0.107.1 휠 내 존재/안정성 미확인**(공식 문서는 client-side MCP 헬퍼를 TS 전용으로 표기). → **휠 검증 게이트**: `python -c "from anthropic.lib.tools.mcp import async_mcp_tool"` 통과 확인, 실패 시 `session.call_tool()` 호출 + `CallToolResult` 매핑하는 **수제 래퍼** 폴백.
  - **tool-search는 베타헤더가 아니라 툴 타입** — `tool_search_tool_bm25_20251119`(자연어, 음성 의도에 적합) 또는 `tool_search_tool_regex_20251119`를 `tools`에 넣음. ~269개 premiere 툴은 `defer_loading=True`, 핫툴 3~5개 + 검색툴만 비-deferred, 서버별 이름 프리픽스(`premiere_*`).
  - **premiere-pro-mcp**(leancoderkavy, ~269툴)는 파일-IPC + CEP 폴링 → **호출당 수백 ms** → **음성 핫패스 금지**. 실제 `dist/index.js` 경로·`PREMIERE_TEMP_DIR` 확인 필요. (Phase 2)
  - 장수명 루프: N개 stdio 세션을 **AsyncExitStack로 상시 오픈**, 호출당 타임아웃, ping/health, 크래시→재spawn→re-list→hot-swap.
  - 이종 tools 리스트(web_search dict + 함수 + MCP) 공존 — runner가 서버사이드 dict를 **통째로 API에 전달(로컬 실행 시도 X)** 하는지 **통합 테스트**.

### 6.6 오케스트레이션 / UX

- **결정:** 단일 asyncio 오케스트레이터 + 상태 기계(§5.1). **PTT 우선**(AEC 문제 회피). 메뉴바는 Phase 2.
- **구성요소(핀):** `sounddevice==0.5.5`(arm64 휠 PortAudio 번들), `asyncio`, `pynput`, (Phase2) `rumps`+`py2app`+launchd, (Phase2) Silero VAD(ONNX), openWakeWord/Porcupine.
- **barge-in(말 끊기):** PTT 다시 누름 → **링버퍼 비우기 + `OutputStream.abort()` + 스트림 재오픈** + **Claude 스트림 Task 취소(취소를 await해 `async with messages.stream()` 정리 → httpx 연결 닫힘)**.
- **문장 스트리밍 재생:** producer가 문장 N 합성하는 동안 N-1 재생(ring buffer가 OutputStream 콜백 공급). 첫 청크 공격적 flush로 time-to-first-audio 최소화.
- ⚠️ **검증이 잡은 함정:**
  - **`sd.stop()`은 우리 구조에서 안 먹힘**(그건 `sd.play()`/`sd.rec()`의 숨은 스트림용). 사용자 OutputStream은 **`abort()`** + 재오픈.
  - sounddevice는 **네이티브 asyncio 없음** → PortAudio 콜백 스레드를 `loop.call_soon_threadsafe`/`janus`/`asyncio.Queue`로 브리지.
  - **PTT = Right-Option**은 `GlobalHotKeys`(비-모디파이어 키 필요) 불가 → **raw `keyboard.Listener`로 `Key.alt_r` on_press/on_release**.
  - **AEC(에코 제거):** `python-webrtc-audio-processing`은 사실상 미유지·arm64 휠 없음 → **파이썬 AEC 불가로 간주**. v1 핸즈프리는 **PTT + 헤드폰**. 오픈스피커 AEC(macOS VoiceProcessingIO 브리지)는 미래/스코프 외.
  - VAD는 **Silero ONNX(onnxruntime)** 로 — torch만을 위해 끌어오지 말 것.
  - **패키징 현실:** py2app가 torch/onnxruntime/ctranslate2 네이티브 dylib을 자주 누락(런타임 에러), 번들 ~GB. → **Phase 1은 .app 대신 launchd로 도는 venv 스크립트**로 배포. .app은 Phase 2.
  - TCC 권한(Microphone/Input Monitoring/Accessibility)은 **번들 id**에 부여 — 터미널 실행 권한은 전이 안 됨.

---

## 7. Phase 1 (v1) — 산출물과 완료 기준

### 산출물
1. `jarvis/` 패키지: 위 모듈 레이아웃의 PTT→STT→Brain→TTS→VC→재생 **끝-끝 루프**.
2. STT: mlx-whisper 한국어, 시작 시 warm.
3. Brain: AsyncAnthropic 스트리밍 + **수동 tool-use 루프(게이팅)** + 메모리 스토어 + 자비스 한국어 페르소나(캐시).
4. TTS+VC: MeloTTS-KR(격리 프로세스) → RVC 자비스 음색. **부트스트랩**으로 기존 커뮤니티 자비스 RVC 모델 또는 임시 음색으로 먼저 말하게 하고, §8 학습 모델 완성 시 교체.
5. 스타터 도구: `web_search`(서버사이드), `time_weather`(로컬). 도구 레지스트리 + (스텁) MCP 슬롯.
6. `voice_training/` 학습 루트 스크립트(§8).
7. 설정/권한 가이드(TCC 권한, HF_HUB_OFFLINE, Keychain 키).

### 완료 기준 (Acceptance)
- [ ] PTT로 한국어 질문 → 5초 내(대화 경로) 자비스 음색 한국어 음성 응답.
- [ ] 도구가 필요한 요청("3 더하기 5 알려주고 메모해줘" 등 로컬 도구) → 도구 호출 → 음성 응답. 되돌릴 수 없는 도구는 음성 확인 게이트 동작.
- [ ] 세션 종료 후 재시작해도 메모리(이름·선호) 유지.
- [ ] `usage.cache_read_input_tokens > 0`(캐시 동작) 확인.
- [ ] barge-in: 말하는 중 PTT로 끊으면 즉시 멈추고 새 입력 받음(연결 누수 없음).
- [ ] STT/TTS/RVC가 **맥 로컬**에서 동작(브레인만 네트워크).

---

## 8. 자비스 음성 학습 루트 (1회성, `voice_training/`)

> "자비스 대사 클립도 알아서 받아서 해" — 아래 파이프라인을 스크립트화하고, **실제 다운로드·학습은 구현 단계에서 실행**한다(저작권상 사용자가 검수한 URL 목록 권장).

### 8.1 Stage A — 수집·전처리 (맥 로컬, 빠름)
1. **수집:** `yt-dlp -x --audio-format wav --audio-quality 0` 로 "JARVIS all lines / supercut / best moments(Paul Bettany)" 컴필레이션. 배경 스코어 적은 클립 선호(아이언맨1 랩/첫 부팅 장면이 가장 깨끗). 검색 예: `JARVIS all lines Iron Man`, `JARVIS supercut Paul Bettany`.
2. **보컬 분리:** `audio-separator==0.44.2`(MIT, Python≥3.10) + **BS-Roformer `model_bs_roformer_ep_317_sdr_12.9755.ckpt`**, 애플실리콘 **CoreMLExecutionProvider**(`--env_info`로 확인). 폴백 `demucs-mlx`/`htdemucs`.
3. **분할:** `ffmpeg silenceremove` 또는 `pydub split_on_silence`(3–12초 조각).
4. **정규화:** `ffmpeg loudnorm`.
5. **잡음 정리:** **`noisereduce`(CPU, 기본)** — ⚠️ `resemble-enhance`는 의존성 취약(Python 3.13 빌드 깨짐) → 옵션, 쓰면 Colab.
6. **리샘플:** RVC용 `ffmpeg -ar 40000 -ac 1 -sample_fmt s16` (GPT-SoVITS 대안 시 `-ar 32000 -ac 1`).
7. **수동 검수:** 음악 누수·중첩·SFX 있는 조각 제거. **작고 깨끗한 데이터셋 > 크고 더러운 것.**

### 8.2 Stage B — 학습 (Colab/빌린 GPU)
- **RVC v2** 학습(~150–300 epoch, batch ~40) → `<name>_e<epoch>_s<step>.pth` + `added_*.index` → 맥으로 복사.
- 데이터 목표: **RVC ~10–30분** 깨끗한 음성(40k mono 16-bit). (GPT-SoVITS 대안은 few-shot ~5–10분, 32k.)
- ⚠️ Mac MPS 학습은 품질 저하 → **반드시 GPU/Colab.**

### 8.3 환경 핀
- prep 환경 **Python 3.10/3.11**(3.13 금지 — audio-separator/resemble-enhance 빌드 깨짐).
- RVC macOS: **`faiss-cpu>=1.7.2`**, `brew install swig`.

### 8.4 MVP 트릭
학습 완료 전: 기존 커뮤니티 자비스 RVC `.pth`로 부트스트랩하거나 임시 음색으로 먼저 말하게 하고, 자체 학습 모델 완성 시 슬롯 교체.

### 8.5 보존 정책
원본 스크랩 오디오는 데이터셋 빌드 후 **자동 삭제**(저작권 풋프린트 최소화).

### 8.6 ⚠️ 저작권·개인사용 (스펙 하드 항목)
자비스 = 폴 베타니 음성, Marvel/Disney IP + 배우의 음성 퍼블리시티권. 본 클립은 **개인용·로컬 모델 학습 목적만**으로 받는다. **데이터셋·클론 모델·그 출력물을 재배포·게시·판매·공유하지 않는다. 배우를 공개적으로 사칭하지 않는다.** 클론 음성은 **개인 사용 한정**. (YouTube ToS상 대량 다운로드는 위배 소지 — yt-dlp `-U` 유지, 가급적 검수된 URL만.)

---

## 9. 횡단 관심사

### 9.1 "완전 로컬"의 정확한 의미 (중요)
**두뇌는 클라우드(Claude API)다.** 매 턴이 `api.anthropic.com`으로의 HTTPS 호출 — 네트워크 없으면 두뇌 없음. 따라서 **"로컬"은 STT/TTS/음색변환/오케스트레이션에만** 적용된다. 서버사이드 `web_search`도 비로컬. 진짜 오프라인 폴백이 필요하면 로컬 MLX/llama.cpp 모델(8–30GB RAM)을 추가해야 하나 **v1 비목표**(품질·자원상). → **사용자 확인 필요(§11).**

### 9.2 프라이버시·데이터 유출
모든 발화 + 주입 메모리가 Anthropic으로 전송됨. **메모리 중 디바이스를 떠나도 되는 범위를 정의**(개인 집사이므로 민감정보 분리). API 키는 Keychain.

### 9.3 모델 핀·은퇴
하이픈 ID만 유효(`claude-haiku-4-5`, 점 표기 무효). 스냅샷 핀 + 분기 계획(예: Sonnet 4 / Opus 4는 2026-06-15 API 은퇴). 베타 표면(`mid-conversation-system`, 메모리툴, tool-search)은 SDK 버전 핀.

### 9.4 지연 예산 (목표)
대화 경로 felt latency ≈ STT finalize(0.5–1.2s) + Claude TTFT(Haiku ~0.4–1s) + TTS 첫오디오(수백 ms) + RVC(문장단위). **도구 턴은 멀티초 — 음성 필러로 가린다.** 측정 게이트: 사용자 실제 맥에서 끝-끝 측정 후 기본 모델 분기 확정.

### 9.5 권한 (macOS TCC)
Microphone, Input Monitoring/Accessibility(pynput) — 실행 주체(venv 스크립트 vs .app)별 별도 부여, **조용히 실패** 주의.

---

## 10. 의존성·런타임 전략

- **2개 venv:** ① 메인(`anthropic[mcp]`, `mlx-whisper`, `mlx-rvc`, `sounddevice`, `pynput`, `mcp`) ② TTS 워커(`MeloTTS` + 고정 옛 torch/transformers + `python-mecab-ko`). 프로세스 간 IPC.
- Python **3.10/3.11**(mcp 익스트라·MeCab·prep 호환).
- 핀: `anthropic==0.107.1`, `mcp==1.27.x`, `mlx-whisper==0.4.3`(+mlx), `sounddevice==0.5.5`, `audio-separator==0.44.2`, `faiss-cpu>=1.7.2`.
- 1회성 GPU/Colab: RVC 학습(필수), (옵션) Whisper 한국어 fine-tune, (Phase2) 커스텀 한국어 웨이크워드.

---

## 11. 아직 사용자 결정이 필요한 열린 질문

1. **맥 사양(칩 + RAM)?** — RVC+TTS 동시 상주 ~16GB+ 권장. 8GB면 양자화/품질 조정 필요. (RTF·헤드룸 결정)
2. **"완전 로컬" 만족 여부:** 두뇌가 클라우드여도 OK? (OK가 기본 가정. 오프라인 폴백 LLM은 v1 비목표)
3. **자비스 음성 소스:** 직접 줄 클립/링크가 있나, 아니면 내가 검수 URL 목록으로 자동 수집? (저작권상 검수 권장)
4. **음색 품질 vs 차분한 말투:** 아키텍처 A(발음 보장, 억양은 MeloTTS)로 시작 → 자비스 특유 톤까지 원하면 B(GPT-SoVITS) 실험.
5. **대화/작업 라우팅:** 키워드 휴리스틱(권장, 빠름) vs 분류 호출(라운드트립 추가 — 음성 핫패스 비권장).

---

## 12. 후속 로드맵

- **Phase 2:** 웨이크워드("자비스" — Porcupine 유료/커스텀 openWakeWord 검토), 맥/앱 제어 도구, **`premiere-pro-mcp` 실연결**, 메뉴바(.app) 패키징, (옵션) 오픈스피커 AEC.
- **Phase 3:** 멀티스텝 워크플로(리코 파이프라인 등), computer-use, 일상 자동화.

각 Phase = 자체 스펙 → 플랜 → 구현 사이클.
