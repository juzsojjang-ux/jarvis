# 설계: 전권 위임 모드 (자비스 권한 확장)

날짜: 2026-06-11
상태: 사용자 승인됨(AskUserQuestion: "전권 위임 모드 추가" 선택)
선행: 풀 도구 개방(3a)·화면 제어 모드(3c)·아이폰 원격

## 목표

"실제 자비스처럼 매번 안 묻게" — 음성으로 **"전권 모드 켜줘"** 하면 그동안
파괴적 도구(Bash/Write/Edit)도 음성 확인 없이 바로 실행한다. 일정 시간 뒤
자동 만료(켠 채 잊기 방지). 화면 제어 모드(CONTROL_GATE)와 같은 검증된
게이트 패턴.

## 핵심 안전 경계 (바뀌지 않음)

1. **원격(아이폰)은 전권 모드와 무관하게 읽기 전용 유지.** `_can_use_tool`의
   `remote_mode` 검사가 최상단이라, 전권 모드가 켜져 있어도 원격 턴은 기존
   읽기 허용목록만 통과한다. 밖에서 오인식으로 집 맥이 털리는 일 차단.
2. **명시적 음성 토글 + TTL 만료**가 위험을 한정한다. "전권 줬다"는 사용자의
   분명한 행동이 있을 때만 자동 실행되고, 잊어도 스스로 닫힌다.
3. confirm 콜백 미주입 시 기존처럼 Deny(전권 모드 OFF일 때).

## 컴포넌트

### `jarvis/core/control_gate.py` — TrustGate 추가
`ControlGate`와 동일한 구조(주입 시계 + 락 + TTL)의 `TrustGate` +
모듈 싱글턴 `TRUST_GATE`. enable(ttl)/disable/is_on(). DRY를 위해 ControlGate를
공통 베이스로 추출하지 않고(작고 독립적), 같은 모양으로 둔다 — 두 게이트의
의미가 달라 분리 유지가 더 명확하다.

### `jarvis/brain/subscription.py` — `_can_use_tool` 전권 자동 허용
`base = tool_name.split("__")[-1]` 다음, `if self._confirm is None:` 앞에:
```python
if TRUST_GATE.is_on():
    return PermissionResultAllow()  # 전권 위임 모드 — 확인 없이 실행
```
위치가 핵심: **remote_mode 검사 뒤**(원격은 여전히 차단), 일반 confirm 앞.
TRUST_GATE를 모듈 상단에서 import.

### `jarvis/core/orchestrator.py` — 음성 토글
`_control_command`/`_toggle_control`과 같은 모양의 `_trust_command`/
`_toggle_trust`. `_pipeline_text` 검사 순서: ① control 토글 → ② **trust 토글**
→ ③ interpret 토글 → ④ interpret 턴 → ⑤ 두뇌.
- `_trust_command(text)`: "전권" 포함 + 켜/꺼 단어("켜져/켜졌" 상태질문 제외,
  control과 같은 엄격 매칭). "전권 모드"·"전권"·"전권 위임" 모두 매칭.
- `_toggle_trust(cmd)`: on이면 `TRUST_GATE.enable(settings.trust_mode_ttl_s)`,
  off면 disable. 안내 발화("전권을 위임받았습니다, 주인님."/"전권 모드를
  껐습니다."). 화면 제어 모드처럼 턴 비탈취 — 게이트만 연다.

### 설정
`trust_mode_ttl_s: float = 600.0` (10분 — 화면 제어보다 길게. 작업하는 동안
유지되도록. 잊어도 10분 후 자동 잠금).

## 데이터 흐름
```
"전권 모드 켜줘" → TRUST_GATE.enable(600) + "전권을 위임받았습니다"
"바탕화면 임시파일 다 지워줘" → 두뇌가 Bash rm 호출
   → _can_use_tool: remote_mode? No → TRUST_GATE.is_on()? Yes → Allow(확인 없이)
(10분 경과 또는 "전권 모드 꺼줘") → TRUST_GATE.disable → 이후 다시 음성 확인
```

## 에러 처리
- TTL 만료는 is_on()이 매 호출 시계 비교로 처리(백그라운드 타이머 없음).
- 전권 OFF + confirm 미주입 → 기존대로 Deny.

## 테스트
- TrustGate: off 기본, enable 후 on, ttl 경과 후 off, disable 즉시 off(주입 시계).
- `_can_use_tool`: TRUST_GATE on이면 Bash가 confirm 없이 Allow(가짜 confirm
  호출 0회); off면 기존 confirm 경로; **remote_mode=True면 전권 on이어도 Bash
  Deny**(원격 우선 — 보안 핵심 테스트).
- 오케스트레이터: `_trust_command` 매칭(전권+켜/꺼, "켜져" 제외, "통역/화면제어"
  무간섭), `_toggle_trust`가 TRUST_GATE enable/disable+안내, 턴 비탈취(토글 후
  일반 질문은 두뇌로).
- config: trust_mode_ttl_s == 600.0.
- 라이브: "전권 모드 켜줘" → 파일 작업이 확인 없이 실행 → "꺼줘" → 다시 확인.
