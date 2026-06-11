# 설계: 외부 발송 (메일·메시지 보내기)

날짜: 2026-06-11
상태: 사용자 승인됨(AskUserQuestion: "외부 발송" 선택)

## 목표

지금은 메시지·메일을 **읽기만** 한다. 보내기를 추가하되, 발송은 되돌릴 수
없는 외부 작업이라 **반드시 발송 전 음성 확인**을 받는다.

## 핵심 안전 설계

기존 `mcp__jarvis__*` 도구는 `_can_use_tool`에서 **전부 자동 허용**(읽기·무해
가정)된다. 발송 도구는 이 자동 허용에서 **제외**해 confirm 경로로 보낸다.

- `SubscriptionBrain._GUARDED_JARVIS = frozenset({"send_message", "send_mail"})`.
- `_can_use_tool`의 `if tool_name.startswith("mcp__jarvis__")` 자동 허용 분기를
  수정: base가 `_GUARDED_JARVIS`에 있으면 자동 허용하지 말고 아래 confirm 경로로
  흐르게 한다(early-return 안 함).
- 흐름상 그 도구는 → 전권 모드면 자동(TRUST_GATE 분기, 일관성) → 아니면
  `_confirm`로 음성 확인 → 미주입이면 Deny. 즉 발송은 **전권 모드이거나 음성
  "네" 확인**일 때만 나간다.
- **원격(아이폰)은 발송 불가**: `_REMOTE_SAFE_JARVIS`에 send_*를 넣지 않으므로
  remote_mode 분기에서 자동 차단. (밖에서 오인식으로 엉뚱한 발송 방지.)

## confirm 프롬프트 (발송 내용 표시)

`_confirm_prompt`에 케이스 추가 — 누구에게 무엇을 보내는지 음성으로 확인:
- send_message: `"{수신자}에게 '{본문 앞 40자}' 보낼까요?"`
- send_mail: `"{받는사람}에게 '{제목}' 메일 보낼까요?"`
입력 키는 도구 인자(아래)와 일치시킨다. tool 이름은 `_can_use_tool`이 넘기는
base("send_message"/"send_mail").

## 도구 (jarvis_mcp.py) — 읽기 도구와 같은 규약

주입형 runner, 절대 raise 안 함, 한국어 안내 문자열. AppleScript 첫 발송 시
자동화 권한 팝업.

### `send_message_action(recipient, text, runner=subprocess.run) -> str`
- 빈 recipient/text → 안내("받는 사람과 내용을 알려주세요.").
- AppleScript Messages: 우선 iMessage 서비스로 전송, 핸들(전화/이메일/이름)로
  buddy 지정. 따옴표 이스케이프(`"`→`\"`)는 안전 처리.
- 성공 → `"{recipient}에게 메시지를 보냈습니다."`, 실패 → 안내.

### `send_mail_action(to, subject, body, runner=subprocess.run) -> str`
- 빈 to → 안내. subject/body 비어도 발송은 허용(제목 없이 가능)하되 to는 필수.
- AppleScript Mail: 새 outgoing message 만들고 to recipient 추가 후 `send`.
- 성공 → `"{to}에게 메일을 보냈습니다."`, 실패 → 안내.

### @tool 래퍼 + 등록
- `send_message`(properties: recipient, text; required 둘 다)
- `send_mail`(properties: to, subject, body; required to)
- `build_jarvis_mcp_server`의 tools 리스트 + `JARVIS_TOOL_NAMES`에 등록(총 30개).
- 두뇌 지침(_GUIDANCE_EN/KO)에 1문장: "메시지·메일을 **보낼** 땐 send_message/
  send_mail을 쓰되, 시스템이 발송 전 확인을 받는다(원격에선 불가)."

## 에러 처리
- AppleScript 실패·권한 부재 → 안내 문자열(raise 금지).
- 따옴표·개행 포함 본문도 깨지지 않게 이스케이프.

## 테스트
- send_message_action: 가짜 runner에 osascript 전달 확인, 빈 인자 안내,
  따옴표 이스케이프, 실패(예외) 안내.
- send_mail_action: 같은 식 + 빈 to 안내 + subject/body 옵셔널.
- `_can_use_tool`:
  - `mcp__jarvis__send_message`는 **자동 허용 안 됨** — confirm 호출됨(가짜
    confirm True→Allow, False→Deny), 미주입→Deny.
  - `mcp__jarvis__get_time`은 여전히 자동 허용(회귀 없음).
  - remote_mode=True면 `send_message` Deny("원격").
  - TRUST_GATE on이면 `send_message`도 confirm 없이 Allow.
- `_confirm_prompt`: send_message/send_mail 프롬프트에 수신자·내용 일부 포함.
- JARVIS_TOOL_NAMES에 send_message·send_mail 등록(30개).
- 라이브: "민지에게 곧 도착한다고 메시지 보내줘" → "민지에게 '곧 도착' 보낼까요?"
  → "네" → 발송. "아니" → 취소.
