# 설계: 대화 기억·맥락 (자비스 능력 확장)

날짜: 2026-06-11
상태: 사용자 승인됨(AskUserQuestion: "대화 기억·맥락" 선택)

## 현황 (조사 결과)

`SubscriptionBrain.respond`는 영속 `ClaudeSDKClient`(`_ensure_client`)에
`query`를 반복하므로 **세션 내 대화 맥락은 이미 유지된다**. 두 갭만 메우면 된다:

1. **재연결 시 맥락 소실**: `_ensure_client(thinking, model)`이 deep-think
   트리거("깊게 생각")나 모델 전환에서 `_client_key`가 바뀌면 disconnect 후
   새 client를 만든다 → 그 순간 SDK 세션 히스토리가 리셋.
2. **재시작 시 맥락 소실**: 프로세스가 꺼지면 세션이 사라진다.

## 목표

최근 대화 몇 턴을 자비스가 **자체 보관**하고, **새 client가 생길 때(재연결·
재시작) 첫 질의에 그 맥락을 1회 주입**한다. 이러면 deep-think 후에도, 재시작
후에도 "아까 그거"가 이어진다. 토큰 낭비 없이 — 영속 client는 그 후 스스로
세션을 누적하므로 주입은 재연결 직후 1회뿐.

## 컴포넌트

### `jarvis/brain/history.py` — ConversationHistory
순수·테스트 가능한 작은 클래스:
- `ConversationHistory(path, max_turns=6)`. 한 턴 = (user, assistant) 쌍.
- `add(user: str, assistant: str)`: 추가 후 max_turns 초과분 잘라내고 디스크에
  저장(JSONL, 한 줄=한 턴, 원자적 write — temp+replace). 빈 문자열은 무시.
- `load()`: 부팅 시 디스크에서 최근 max_turns 로드(파일 없으면 빈 상태, 손상
  라인은 건너뜀 — 절대 raise 안 함).
- `as_context() -> str`: 주입용 텍스트. 비었으면 "". 형식:
  ```
  [이전 대화 맥락 — 참고만, 다시 답하지 말 것]
  주인님: {user}
  자비스: {assistant}
  ...
  [현재 질문]
  ```
  마지막 "[현재 질문]" 줄로 끝나, 호출부가 실제 질문을 이어붙인다.
- 기본 경로 `~/.jarvis/history.jsonl`.

### `SubscriptionBrain` 연동
- `__init__`: `self._history`(주입 가능, 기본 `ConversationHistory()` +
  `load()`), `self._primed = False`.
- `_ensure_client`가 **새 client를 생성할 때마다** `self._primed = False`로
  표시(재연결·최초연결 모두). 기존 client 재사용이면 건드리지 않는다.
- `respond(user_text)`:
  - 질의 텍스트 결정: `_primed`가 False이고 history가 비어있지 않으면
    `query_text = history.as_context() + user_text`, 그 후 `_primed = True`.
    아니면 `query_text = user_text`.
  - 응답 스트림이 끝나면 영어 답(yield된 spoken 합본)을 모아
    `self._history.add(user_text, spoken_full)` 저장. (자막용 한국어 말고
    영어 본문 — 맥락 재주입도 영어 지침과 일관.)
  - 주입 맥락은 발화·자막에 영향 없음(query 입력일 뿐, 출력은 그대로 파싱).
- `warm()`의 throwaway "hi"는 `_primed`를 소비하면 안 된다 → warm은 history
  주입 경로를 타지 않게 별도(현재도 client.query 직접 호출이라 respond 미경유 —
  영향 없음, 단 warm 후 `_primed`는 False 유지해야 첫 실제 턴이 주입받는다).

### 부팅
`__main__`이나 factory에서 brain 생성 시 history.load()는 ConversationHistory
생성자에서 자동(또는 brain.__init__에서 1회). 추가 배선 불필요.

### 잊기(선택, YAGNI 경계)
"대화 잊어줘" 음성 명령은 이번 범위 밖 — 단, history.clear()(파일 비우기)는
구현해 두면 후속 연결이 쉽다. clear()만 추가하고 음성 토글은 생략.

## 에러 처리
- 디스크 read/write 실패는 조용히 무시(메모리 상태로 계속). 대화는 기억보다
  우선.
- 손상 JSONL 라인은 건너뛴다.

## 테스트
- ConversationHistory: add→load 왕복, max_turns 초과 시 오래된 것 삭제,
  as_context 형식(빈/비빈), 손상 라인 skip, 원자적 저장(temp 잔존 없음),
  clear.
- SubscriptionBrain(가짜 client_cls): 재연결 후 첫 query에 맥락 prepend +
  _primed True로 두 번째 query엔 미주입; respond 종료 후 history.add 호출;
  history 비었으면 주입 안 함; warm이 _primed 안 건드림.
- 통합: deep-think로 _ensure_client 재연결 → 다음 respond가 맥락 주입.
- 라이브: "내 이름은 성재야" → (deep-think 트리거로 재연결 유발) "내 이름 뭐랬지?"
  → 기억. 재시작 후에도 직전 대화 한 토막 기억.
