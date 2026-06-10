# 설계: 정보 팩 (3단계 능력 확장 — 3b)

날짜: 2026-06-11
상태: 사용자 승인됨
선행: 3a 액션 팩 + 풀 도구 개방(가동 중)

## 목표

음성 비서에 특화된 정보 기능 3종. 파일 찾기/읽기는 풀 도구 개방(3a)으로
이미 자비스가 Glob/Grep/Read로 직접 하므로 제외.

1. **통역 모드** — 한↔영 실시간 통역
2. **메시지·메일 읽기** — 읽기 전용 MCP 도구 2개
3. **자동 기억 강화** — 명시 없이도 선호·약속 자동 저장

## A. 통역 모드

### 동작
- "통역 모드 켜줘" → 진입. 한국어로 말하면 **영어로 발화**, 영어로 말하면
  **한국어로 발화**. "통역 모드 꺼줘" → 평소 자비스 복귀.
- 두뇌의 전체 도구 경로를 거치지 않고 **번역 전용 경량 경로**로 직행(빠름,
  도구·위트 없음).

### 언어 감지
- STT를 `language=None`(자동 감지)로 변환 → 결과 텍스트의 **한글 포함 여부**로
  방향 결정: 한글 있으면 source=ko→영어로, 없으면 source=en→한국어로.
  (`detect_lang(text) -> "ko"|"en"`: 한글 음절 `가–힣` 존재 검사.)

### TTS 제약과 출력 경로
- 현 TTS는 Pocket(**영어 전용**). 통역의 한국어 출력은 Pocket으로 불가능하므로
  **macOS `say -v <ko voice>`로 직접 재생**(기본 출력장치로 나감). 영어 출력은
  기존 `_speak`(Pocket) 경로 그대로.
- 한국어 보이스는 설정 `interpret_ko_voice`(기본 "Yuna"; 부재 시 첫 ko_KR
  보이스로 폴백). `interpret_speak_korean(text, voice, runner)` 헬퍼.

### 컴포넌트
- `jarvis/core/interpret.py`:
  - `detect_lang(text) -> str` (순수, 단위테스트).
  - `interpret_speak_korean(text, voice="Yuna", runner=subprocess.run)` —
    `say -v voice text` (timeout 30, 실패 시 조용히 무시).
- `SubscriptionBrain.translate(text, target_lang) -> str`: 도구 없는 1회성
  질의. `ClaudeSDKClient`를 `ClaudeAgentOptions(system_prompt="…번역만…",
  allowed_tools=[], max_turns=1, can_use_tool 없음, setting_sources=[], env)`로
  새로 열어 `query(text)` → 응답 텍스트 수집 → 닫음. 시스템 프롬프트:
  "Translate the given sentence into {target}. Output ONLY the translation —
  no explanation, quotes, or notes." 주입 가능(`_client_cls`/`_options_cls`
  재사용, 테스트는 가짜로 대체). 오케스트레이터는 `brain.translate`를 직접
  호출하되, `interpret_translate`(주입형 async fn)로 추상화해 테스트에서 가짜
  주입.
- 오케스트레이터:
  - `self.interpret_mode = False`.
  - `_interpret_command(text) -> "on"|"off"|None` (한국어 구문 매칭:
    "통역"+"켜/꺼/시작/종료/끄"). `_pipeline_text` 진입부에서 먼저 검사 —
    토글이면 모드 전환 + 짧은 안내 발화 후 종료.
  - 모드 ON이고 토글 명령이 아니면 `_interpret_turn(text)`: detect_lang →
    반대 언어로 translate → en이면 `_speak`(Pocket), ko면
    `interpret_speak_korean`. follow-up 창 유지(연속 통역).
  - `_pipeline`이 통역 모드일 때는 STT를 `language=None`로 호출(자동 감지).

### 설정
- `interpret_enabled: bool = True`
- `interpret_ko_voice: str = "Yuna"`

## B. 메시지·메일 읽기 (jarvis_mcp 도구)

읽기 전용, 주입형 runner, 절대 raise 안 함, AppleScript 첫 접근 시 자동화
권한 팝업. 보내기·삭제는 풀 도구 개방의 음성 게이트로 두뇌가 처리(여기 없음).

- **`messages_text(count=5, runner)`** — 최근 받은 메시지 N건(발신자|내용).
  AppleScript Messages(`database` chat 접근). 출력 "민지: 도착했어 / …".
  없으면 "최근 메시지가 없습니다." 권한·앱부재 시 안내 문자열.
- **`mail_text(count=5, runner)`** — 안 읽은 메일 N건(발신자|제목). AppleScript
  Mail(`messages whose read status is false`). 출력 "김부장 — 회의 일정 / …".
  없으면 "안 읽은 메일이 없습니다."
- `sources.py` 패턴 차용: `id|a|b` 라인 파싱 헬퍼 재사용 가능하면 재사용,
  아니면 도구 내 간단 split. @tool 래퍼 `get_messages`/`get_unread_mail`,
  JARVIS_TOOL_NAMES 등록(읽기셋 — `_can_use_tool`이 mcp__jarvis__*로 자동 허용).

## C. 자동 기억 강화

- 두뇌 지침(_GUIDANCE_EN/_KO)에 1문장: "대화 중 주인님의 **선호·약속·이름·
  반복 습관** 등 다음에 알면 유용한 개인 정보를 자연스럽게 알게 되면, 묻지 말고
  remember 도구로 조용히 저장하라. 단 잡담·일시적 맥락·민감정보는 저장 금지."
- `remember` 중복 방지: `MemoryStore.remember(note)`가 저장 전 중복 검사 —
  정규화(공백 축약·소문자·구두점 제거)한 note가 기존 `self._text`의 어떤 줄과
  부분일치(한쪽이 다른 쪽 포함)면 저장 스킵하고 조용히 반환. 이렇게 하면
  jarvis_mcp의 remember 도구·자동 기억 둘 다 중복 없이 동작(도구 변경 불필요).
  현 `remember(note)`는 빈/공백만 거르므로 그 직후에 검사 추가.

## 에러 처리
- 통역 translate 실패 → "번역에 실패했습니다" 1회 안내 후 IDLE(모드는 유지).
- 메시지/메일 도구 전부 안내 문자열 반환(raise 금지).
- 통역 모드 중 STT 빈 결과 → 조용히 무시(IDLE).

## 테스트
- `detect_lang`: 한글/영문/혼합/빈문자.
- `interpret_speak_korean`: runner에 `say -v Yuna ...` 전달, 실패 무시.
- 오케스트레이터: `_interpret_command` 토글 매칭, 모드 ON 시 한국어 입력→영어
  translate+_speak 경로 / 영어 입력→ko say 경로(가짜 translate·runner),
  토글 안내 발화, 모드 OFF 시 평소 경로.
- `SubscriptionBrain.translate`: 가짜 client로 시스템 프롬프트·번역문 추출.
- `messages_text`/`mail_text`: 가짜 runner 파싱 + 빈 결과 + 실패.
- `remember` 중복 방지: has_similar True면 저장 스킵.
- 라이브: "통역 모드 켜줘" → "Hello"라 말하면 한국어로, "안녕"이라 말하면
  영어로. "안 읽은 메일 알려줘". 대화 중 "나 매운 거 못 먹어" → 자동 기억.
