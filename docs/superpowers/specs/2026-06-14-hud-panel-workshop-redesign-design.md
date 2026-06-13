# HUD 작업실 패널 재설계 + 오브 알파 — 설계

작성 2026-06-14 · 상태: 설계 확정(구현 대기) · 범위: `jarvis/hud/*`, `jarvis/core/orchestrator.py`, `jarvis/tools/jarvis_mcp.py`, `packaging/jarvis.spec`
레퍼런스: [jarvis-hud-movie-references.md](./jarvis-hud-movie-references.md) (아이언맨/자비스 100+).

## 목표

1. **오브 검정 박스 제거(WebKit)**: SVG 휘도→알파 필터가 WKWebView의 `<video>`에 안 먹어 검정 사각형이 남는 문제를, **알파가 박힌 영상 자산**으로 교체해 해결. macOS=HEVC-알파 .mov, Windows=VP9-알파 .webm.
2. **패널 작업실 재설계**: 우상단 단일 패널 → **오브 중심 방사형 작업실**. 평소 정보 표시도 전부 이 스타일로 통일("패널 전부 교체"). 영화(아이언맨 자비스) 디자인 언어 적용.

## 핵심 결정 (브레인스토밍 합의)

### 1. 두 모드 = 영화 "Omega 위젯"(코너↔중앙 펼침)
기존 expand 토글 재사용. **말하기·생각만으론 전환 안 함**(현 모드 제자리 음성 반응).
- **코너 모드(A, 기본)**: 오브 우하단 소형 + 정보 패널이 그 위로 **세로 스택**. 방해 최소. 텔레메트리는 최소(시계+작업수 1줄).
- **중앙 작업실 모드(B, 확장)**: 오브 중앙으로 커지고 패널이 **주위에 방사 배치**. 메인(두뇌) 패널 + 텔레메트리 패널 + 하단 5게이지 스트립.
- 전환 트리거: ① 두뇌가 패널 띄움(정보 발생) ② "크게 띄워/작게" 음성 ③ notice. 0.4s ease(영화식 단순 zoom/wipe, 과한 연출 금지).

### 2. 패널 내용 = A+B 둘 다
- **메인 패널(두뇌)**: `show_panel` 확장 — 기존 단일 텍스트 **+ 여러 카드**(`[{title, body, tone}]`) 지원. 하위호환 유지.
- **텔레메트리 패널(자비스 자동)**: 진짜 실시간 데이터만. 영화 하단 5위젯(diagnostic·flight·power·radar·nav) 매핑 → **시계 · 네트워크(Tailscale) · 마이크 상태 · CPU/MEM · 백그라운드 작업 수**. 데이터 없으면 해당 게이지 생략(가짜 장식 금지 — Kent Seki "기능 없으면 뺀다").

### 3. 유동 크기
모든 패널이 내용량(글자·줄·카드 수)에 따라 폭·폰트 자동(기존 notice big/huge를 전 패널로 일반화). 코너 스택은 위로, 중앙은 슬롯 안에서.

### 4. 영화 디자인 언어 (확정 값)
- **색**: 시안 `#67C7EB`(글로우), 보조 `#aef`·`#d8f6ff`; 골드/앰버 `#ECBA4F`·`#FBCA03`(오브·경고·호 게이지); 패널 바탕 `rgba(0,8,14,.85)`.
- **타이포**: 지오메트릭 기술 모노(0Arame 근사 — 시스템 `ui-monospace`/`SF Mono` 폴백, 무료 대체 폰트는 구현 시 결정). 헤더 대문자·자간 넓게, 작은 라벨.
- **모티프**: 오브 둘레 **동심원 시안 링 2겹 + 점선 골드 호 게이지(부분 채움, 느린 회전) + 라디얼 틱**; 패널 **코너 브래킷** ⌐ + 헤더 상태점 + 스캔라인; **리더 라인(오브→패널) + 끝점 닷 + 콜아웃 마이크로 라벨**; 텔레메트리 **미니 링 게이지/스파크라인**; **하단 5게이지 스트립**(B); 옅은 그리드(B). 데이터 틱(흐름).
- **모션**: 등장=깊이에서 페이드+확장, 라인이 오브에서 뻗음. 상시=링 느린 회전·틱 흐름·오브 음성 맥동. 전부 은은(과함 금지).

### 5. 오브(알파 영상)
- 자산 2종을 휘도→알파 lumakey로 ffmpeg 인코딩(검정 배경 제거, 가장자리 안티에일리어싱 유지):
  - `orb-alpha.mov` — HEVC+alpha(hvc1), 1100²·24fps, ~17MB → WebKit(WKWebView).
  - `orb-alpha.webm` — VP9+alpha(yuva420p), 1100²·24fps, ~22MB → Chromium(WebView2).
- `<video>`가 **엔진별로 소스 선택**(JS userAgent 분기: WebKit→.mov, 그 외→.webm). SVG `#lumakey` 필터 제거.
- 오브 반응(스케일/글로우/코어/밝기)은 기존 `level` 구동 유지. 밝기 맥동 은은하게.

## 데이터 흐름 / 컴포넌트 경계

- **OrbHub(orb_server.py)**: SSE 페이로드에 `panels` 배열 추가 — `[{id, title, body, kind:"brain"|"telemetry", tone:"cyan"|"gold"|"warn", gauge?}]`.
  - 두뇌 패널 소스(show_panel) + 텔레메트리 소스를 **서버가 병합**해 emit. 기존 `notice`는 단일 brain 패널로 매핑(하위호환). `state/level/text/expand` 유지.
- **텔레메트리 공급자(신규, `jarvis/hud/telemetry.py`)**: 주기적(예 2s)으로 시계·NET·MIC·CPU/MEM·작업수를 수집해 OrbHub에 push. 각 항목은 가용할 때만(psutil 없으면 CPU/MEM 생략 등). orchestrator가 마이크/작업수 상태를 주입.
- **show_panel(jarvis_mcp.py)**: 인자에 선택적 `cards: [{title, body}]` 추가. 단일 텍스트 경로 유지.
- **orb.html**: `panels`를 받아 모드별 슬롯에 렌더(코너=세로 스택 / 중앙=방사 슬롯+리더라인+5게이지). 단일 `#notice` div → 동적 패널 렌더러로 교체. 자막(`#subtitle`) 유지.
- **jarvis.spec**: orb-alpha.mov/webm 번들(플랫폼별 포함 가능). 기존 orb.mp4 번들 제거.

## 단위 경계(독립 검증)

- `telemetry.py`: 순수 수집기(입력 없는 데이터→dict). 단위 테스트로 누락 항목 graceful.
- OrbHub `panels` 계약: state/level/notice/panels/expand emit 회귀 테스트.
- orb.html 렌더러: 패널 수 0~N, 모드 A/B, 유동 크기 분기(브라우저 수동 + 스냅샷).
- 알파 자산: 파일 존재 + 디코드 시 코너 alpha=0·중앙 불투명(빌드/테스트 시 ffprobe/디코드 검증).

## 비목표(YAGNI)

- 두뇌가 패널 위치를 직접 지정(자동 배치만).
- 3D/WebGL 오브(알파 영상으로 충분).
- 0Arame 유료 폰트 번들(근사 폰트로 대체).
- 텔레메트리 항목 무한 확장(위 5종으로 시작).

## 검증

- 맥: 실제 투명 오버레이에서 오브 검정 제거 + 코너/중앙 패널·리더라인·5게이지 육안 확인.
- 윈도우: WebView2에서 동일(webm 알파, 패널) — 실기 필요.
- 회귀: 위 단위 테스트 + 전체 스위트 통과.
