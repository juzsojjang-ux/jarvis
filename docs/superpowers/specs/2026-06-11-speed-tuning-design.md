# 설계: 음성·속도 튜닝 1차 (로드맵 4단계 — 지속 반복)

날짜: 2026-06-11
상태: 사용자 승인됨("다음 단계 진행해" + "알아서 다 해")
선행: 로드맵 ①웨이크 ②능동 ③능력확장(3a/3b/3c) 완료

## 목표

4단계는 "지속 반복" — 이번 1차 이터레이션은 **측정 기반 튜닝의 토대**와
**이미 알려진 지연 3건**을 잡는다. 음색 자체 튜닝(청취 필요)은 사용자
피드백이 있어야 하므로 다음 이터레이션.

## 항목

### A. 턴 지연 계측 (측정 없이는 반복 불가)

매 일반 턴마다 한 줄 로그:
`[지연] STT 0.42s · 두뇌 첫문장 1.31s · 합계 1.73s`

- STT 시간: `_pipeline`(PTT)과 `_handle_wake`(웨이크) 각자 측정해
  `self._last_stt_s`에 기록(웨이크는 게이트+전문 변환 합산).
- 두뇌 첫문장: `_pipeline_text` 일반 경로에서 THINKING 진입부터 첫
  `_speak` 직전까지.
- 출력은 `print` 한 줄(기존 `[웨이크]`/`[통역]` 로그와 같은 결). 포맷은
  순수 함수 `format_latency(stt_s, first_s) -> str`로 분리(단위테스트).
  STT 시간이 없으면(능동 알림 등) STT 부분 생략.

### B. 통역 콜드스타트 제거

현 `translate()`는 호출마다 새 `ClaudeSDKClient`를 열어 첫 통역 턴이
수초 지연(3b 교훈). 개선:
- **방향별 영속 클라이언트 캐시** `self._xlate: dict[str, client]`
  (key=target_lang). 첫 사용 시 `connect()`, 이후 재사용. 실패 시 캐시에서
  제거 후 예외 전파(오케스트레이터가 이미 모드 유지+IDLE 복귀 처리).
- `warm_interpret()`: 두 방향(English/Korean) 클라이언트를 만들고 짧은
  throwaway 질의로 예열(best-effort, 예외 무시).
- 오케스트레이터 `_toggle_interpret("on")`이 **백그라운드 태스크**로
  `brain.warm_interpret()` 호출(hasattr 가드 — api 두뇌엔 없음) — 안내
  발화가 끝나기 전에 예열이 끝나 첫 통역부터 빠르다.
- `close()`가 xlate 클라이언트도 disconnect.

### C. ACK 필러 부팅 프리캐시

`_play_phrase`는 첫 사용 시 합성해 `_ack_cache`에 캐시 — 즉 부팅 후
**첫 ACK 4회는 합성 지연**이 있다. `_play_phrase`에서 합성부를
`_synth_phrase(en) -> ndarray|None`으로 분리하고, `warm_phrases()`가
ACK_FILLERS 4문장+"Yes, sir?"를 미리 합성. `__main__`이 `brain.warm()`
다음에 호출. 실패는 조용히 무시(부팅을 막지 않는다).

### D. 음성 배너 거짓말 수정

`vc_status`가 `vc_backend=="null"`이면 무조건 "멜로TTS 한국어 음성"이라
하지만 실제 기본은 Pocket 영어 자비스 음색. `tts_backend=="pocket"`이면
"음색 변환 꺼짐 — 포켓 TTS 자비스 음색(영어)으로 말합니다."로 분기.
active 플래그는 RVC 전용 의미 그대로 False 유지.

## 테스트

- `format_latency`: STT 있음/없음 포맷.
- 오케스트레이터: 일반 턴 후 `[지연]` 줄 출력(capsys), 통역 토글 on 시
  warm_interpret 태스크 생성(가짜 brain 기록), 프리캐시 후 _ack_cache 채워짐.
- `translate`: 같은 방향 2회 호출 시 클라이언트 1회 생성+connect 1회,
  방향 다르면 2개, close가 disconnect(기존 컨텍스트매니저 테스트를
  connect/disconnect 계약으로 갱신).
- `vc_status`: pocket+null → 포켓 문구, melotts+null → 기존 문구.

## 에러 처리

- 계측은 절대 턴을 깨지 않는다(포맷 실패해도 무시).
- warm 계열 전부 best-effort(예외 삼킴).
- translate 영속 클라이언트 죽으면 다음 호출이 새로 연결.
