# 음성·속도 튜닝 1차 (4단계) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 턴 지연 계측 한 줄 로그 + 통역 콜드스타트 제거(영속 번역 클라이언트+토글 시 예열) + ACK 필러 부팅 프리캐시 + 음성 배너 거짓말 수정.

**Architecture:** 계측은 순수 포맷 함수 + 오케스트레이터 타임스탬프(print 한 줄, 턴을 절대 깨지 않음). 번역은 방향별 영속 `ClaudeSDKClient` 캐시(`_xlate` dict, 실패 시 폐기·재연결), 통역 토글 on이 백그라운드 태스크로 예열. 캔드 프레이즈 합성을 `_synth_phrase`로 분리해 부팅 `warm_phrases()`가 미리 채움.

**Tech Stack:** Python 3.11(.venv), pytest, claude-agent-sdk(주입형 client_cls/options_cls 페이크로 테스트).

**Spec:** `docs/superpowers/specs/2026-06-11-speed-tuning-design.md`

**공통 규칙:** 작업 디렉터리 `/Users/2seongjae/jarvis`, 테스트는 `.venv/bin/python -m pytest`. warm 계열·계측은 전부 best-effort(예외 삼킴). 테스트는 실제 SDK/장치 호출 금지(페이크 주입).

---

### Task 1: vc_status 배너 — Pocket 분기

**Files:**
- Modify: `jarvis/vc/factory.py:80-81` (vc_status의 null 분기)
- Test: `tests/tools/test_voice_status.py` (기존 파일에 추가 — 기존 import 스타일을 따른다)

- [ ] **Step 1: Write the failing tests** — 기존 파일 끝에 추가(기존 테스트의 Settings 생성 방식을 그대로 따른다):

```python
def test_vc_status_null_with_pocket_mentions_pocket():
    s = Settings(vc_backend="null", tts_backend="pocket")
    active, msg = vc_status(s)
    assert active is False
    assert "포켓" in msg and "멜로TTS" not in msg


def test_vc_status_null_with_melotts_keeps_melo_message():
    s = Settings(vc_backend="null", tts_backend="melotts")
    _active, msg = vc_status(s)
    assert "멜로TTS" in msg
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/tools/test_voice_status.py -v` — 새 테스트 FAIL("포켓" 부재).

- [ ] **Step 3: Implement** — `jarvis/vc/factory.py`의

```python
    if settings.vc_backend == "null":
        return (False, "음색 변환 꺼짐 — 멜로TTS 한국어 음성으로 말합니다.")
```

를 다음으로 교체:

```python
    if settings.vc_backend == "null":
        if getattr(settings, "tts_backend", "") == "pocket":
            return (False, "음색 변환 꺼짐 — 포켓 TTS 자비스 음색(영어)으로 말합니다.")
        return (False, "음색 변환 꺼짐 — 멜로TTS 한국어 음성으로 말합니다.")
```

- [ ] **Step 4: Run** 같은 명령 — all passed.
- [ ] **Step 5: Commit** `git add jarvis/vc/factory.py tests/tools/test_voice_status.py && git commit -m "fix(튜닝): 음성 배너 — pocket 백엔드일 때 포켓 자비스 음색으로 표기"`

---

### Task 2: 턴 지연 계측

**Files:**
- Modify: `jarvis/core/orchestrator.py` — 모듈 함수 `format_latency` + `__init__`에 `_last_stt_s` + `_pipeline`/`_handle_wake`/`_pipeline_text`/`announce` 스탬프
- Test: `tests/test_orchestrator.py` (기존 `_make()` 하니스 사용)

- [ ] **Step 1: Write the failing tests** — `tests/test_orchestrator.py` 끝에 추가:

```python
def test_format_latency_with_and_without_stt():
    from jarvis.core.orchestrator import format_latency
    assert format_latency(0.42, 1.31) == "[지연] STT 0.42s · 두뇌 첫문장 1.31s · 합계 1.73s"
    assert format_latency(None, 1.31) == "[지연] 두뇌 첫문장 1.31s"


def test_pipeline_text_prints_latency_line(capsys):
    orch, _pb = _make()

    async def run():
        await orch._pipeline_text("안녕")
    asyncio.run(run())
    assert "[지연]" in capsys.readouterr().out
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/test_orchestrator.py -k latency -v` — FAIL(ImportError).

- [ ] **Step 3: Implement** — `jarvis/core/orchestrator.py`:

(a) 모듈 레벨(클래스 밖, State/import 아래)에 추가:

```python
def format_latency(stt_s: float | None, first_s: float) -> str:
    """튜닝용 한 줄 지연 로그 — 측정 없이는 반복(로드맵 4단계) 불가."""
    if stt_s is None:
        return f"[지연] 두뇌 첫문장 {first_s:.2f}s"
    return (f"[지연] STT {stt_s:.2f}s · 두뇌 첫문장 {first_s:.2f}s"
            f" · 합계 {stt_s + first_s:.2f}s")
```

(b) `__init__`에 `self._last_stt_s: float | None = None` 추가(다른 상태 필드 옆).

(c) `_pipeline`의 transcribe를 감싼다:

```python
            lang = None if self.interpret_mode else self.settings.language
            t0 = asyncio.get_running_loop().time()
            text = await asyncio.to_thread(self.stt.transcribe, pcm, 16000, lang)
            self._last_stt_s = asyncio.get_running_loop().time() - t0
```

(d) `_handle_wake`: try 본문 첫 줄(`loop = asyncio.get_running_loop()` 다음)에 `t0 = loop.time()` 추가, `await self._pipeline_text(command)` 직전에 `self._last_stt_s = loop.time() - t0` 추가(게이트+전문 변환 합산 — 사용자 체감 STT 시간).

(e) `_pipeline_text`의 일반 경로를 다음으로 교체(THINKING 진입부터 tail까지):

```python
        self.state = State.THINKING
        self._publish("thinking")
        t_think = asyncio.get_running_loop().time()
        first_done = False

        def _mark_first() -> None:
            nonlocal first_done
            if first_done:
                return
            first_done = True
            try:
                dt = asyncio.get_running_loop().time() - t_think
                print(format_latency(self._last_stt_s, dt))
            except Exception:  # noqa: BLE001 - 계측이 턴을 깨면 안 된다
                pass
            self._last_stt_s = None

        if ack:
            await self._play_ack()  # "One moment, sir." — 능동 알림은 생략(아무도 안 기다림)
        async for delta in self.brain.respond(text):
            for sentence in self.chunker.feed(delta):
                _mark_first()
                await self._speak(sentence)
        tail = self.chunker.flush()
        if tail:
            _mark_first()
            await self._speak(tail)
```

(f) `announce()` 본문 첫 줄에 `self._last_stt_s = None` 추가(직전 턴의 STT 시간이 능동 알림 지연 줄에 새는 것 방지).

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_orchestrator.py -v` — all passed(기존 테스트 회귀 없음).
- [ ] **Step 5: Commit** `git add jarvis/core/orchestrator.py tests/test_orchestrator.py && git commit -m "feat(튜닝): 턴 지연 계측 — [지연] STT·두뇌 첫문장 한 줄 로그"`

---

### Task 3: translate 영속 클라이언트

**Files:**
- Modify: `jarvis/brain/subscription.py` — `__init__`에 `_xlate`, `translate` 교체+`_ensure_xlate` 추가, `close` 교체
- Test: `tests/brain/test_subscription.py` — 기존 `test_translate_uses_translation_only_options` 갱신 + 재사용 테스트 추가

- [ ] **Step 1: Update/write the failing tests** — `test_translate_uses_translation_only_options`의 `_FakeClient`를 컨텍스트매니저에서 connect/disconnect 계약으로 교체하고, 재사용 테스트를 추가:

```python
def test_translate_uses_translation_only_options():
    import asyncio

    from jarvis.brain.subscription import SubscriptionBrain
    from jarvis.core.config import Settings

    captured = {}

    class _FakeOptions:
        def __init__(self, **kw):
            captured.update(kw)

    class _FakeClient:
        def __init__(self, options=None):
            captured["options_obj"] = options

        async def connect(self):
            captured["connected"] = True

        async def disconnect(self):
            captured["disconnected"] = True

        async def query(self, text):
            captured["query"] = text

        async def receive_response(self):
            class _Blk:
                type = "text"
                text = "Hello, sir."

            class _Msg:
                content = [_Blk()]
            yield _Msg()

    brain = SubscriptionBrain(Settings(), None, "p" * 4096,
                              client_cls=_FakeClient, options_cls=_FakeOptions)
    out = asyncio.run(brain.translate("안녕하세요", "English"))
    assert out == "Hello, sir."
    assert captured["query"] == "안녕하세요"
    assert captured["allowed_tools"] == []
    assert captured["max_turns"] == 1
    assert "English" in captured["system_prompt"]
    assert captured["connected"] is True


def test_translate_reuses_client_per_direction():
    import asyncio

    from jarvis.brain.subscription import SubscriptionBrain
    from jarvis.core.config import Settings

    instances = []

    class _FakeOptions:
        def __init__(self, **kw):
            pass

    class _FakeClient:
        def __init__(self, options=None):
            self.connects = 0
            instances.append(self)

        async def connect(self):
            self.connects += 1

        async def disconnect(self):
            pass

        async def query(self, text):
            pass

        async def receive_response(self):
            class _Blk:
                type = "text"
                text = "ok"

            class _Msg:
                content = [_Blk()]
            yield _Msg()

    brain = SubscriptionBrain(Settings(), None, "p" * 4096,
                              client_cls=_FakeClient, options_cls=_FakeOptions)

    async def run():
        await brain.translate("a", "English")
        await brain.translate("b", "English")   # 같은 방향 — 재사용
        await brain.translate("c", "Korean")    # 다른 방향 — 새 클라이언트
        await brain.close()

    asyncio.run(run())
    assert len(instances) == 2
    assert all(c.connects == 1 for c in instances)


def test_translate_failure_drops_cached_client():
    import asyncio

    import pytest

    from jarvis.brain.subscription import SubscriptionBrain
    from jarvis.core.config import Settings

    instances = []

    class _FakeOptions:
        def __init__(self, **kw):
            pass

    class _BoomClient:
        def __init__(self, options=None):
            instances.append(self)

        async def connect(self):
            pass

        async def disconnect(self):
            pass

        async def query(self, text):
            raise RuntimeError("dead session")

        async def receive_response(self):
            yield  # pragma: no cover

    brain = SubscriptionBrain(Settings(), None, "p" * 4096,
                              client_cls=_BoomClient, options_cls=_FakeOptions)

    async def run():
        with pytest.raises(RuntimeError):
            await brain.translate("a", "English")
        with pytest.raises(RuntimeError):
            await brain.translate("b", "English")

    asyncio.run(run())
    assert len(instances) == 2  # 실패가 캐시를 비워 다음 호출이 새로 연결
```

- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/brain/test_subscription.py -k translate -v` — FAIL.

- [ ] **Step 3: Implement** — `jarvis/brain/subscription.py`:

(a) `__init__`의 `self._client_key ... = None` 줄 다음에:

```python
        self._xlate: dict[str, Any] = {}  # 통역용 방향별 영속 클라이언트(콜드스타트 제거)
```

(b) `translate`를 다음으로 교체(+`_ensure_xlate` 추가):

```python
    async def _ensure_xlate(self, target_lang: str) -> Any:
        client = self._xlate.get(target_lang)
        if client is None:
            self._ensure_sdk()
            env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
            opts = self._options_cls(
                system_prompt=(f"Translate the given sentence into {target_lang}. "
                               "Output ONLY the translation — no explanation, quotes, "
                               "or notes."),
                allowed_tools=[],
                setting_sources=[],
                max_turns=1,
                env=env,
            )
            client = self._client_cls(options=opts)
            await client.connect()
            self._xlate[target_lang] = client
        return client

    async def translate(self, text: str, target_lang: str) -> str:
        """도구 없는 번역 질의 — 방향별 영속 클라이언트 재사용(첫 통역 콜드스타트 제거)."""
        client = await self._ensure_xlate(target_lang)
        out: list[str] = []
        try:
            await client.query(text)
            async for msg in client.receive_response():
                for block in getattr(msg, "content", []) or []:
                    if getattr(block, "type", "") == "text":
                        out.append(getattr(block, "text", ""))
        except Exception:
            self._xlate.pop(target_lang, None)  # 죽은 세션 폐기 — 다음 호출이 재연결
            raise
        return "".join(out).strip()

    async def warm_interpret(self) -> None:
        """통역 토글 on에서 백그라운드 호출 — 두 방향을 미리 연결·예열(best-effort)."""
        for target in ("English", "Korean"):
            try:
                await self.translate("hi", target)
            except Exception:  # noqa: BLE001 - 예열 실패는 무해
                pass
```

(c) `close`를 다음으로 교체:

```python
    async def close(self) -> None:
        for client in (self._client, *self._xlate.values()):
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001
                    pass
        self._client = None
        self._xlate = {}
```

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/brain/ -v` — all passed.
- [ ] **Step 5: Commit** `git add jarvis/brain/subscription.py tests/brain/test_subscription.py && git commit -m "feat(튜닝): translate 방향별 영속 클라이언트+warm_interpret — 통역 콜드스타트 제거"`

---

### Task 4: 통역 토글 시 백그라운드 예열

**Files:**
- Modify: `jarvis/core/orchestrator.py` — `__init__`에 `_warm_task`, `_toggle_interpret`에 예열 훅
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**:

```python
def test_interpret_toggle_on_warms_translate():
    orch, _pb = _make()
    warmed = []

    class _WarmBrain(_XlateBrain):
        async def warm_interpret(self):
            warmed.append(True)

    orch.brain = _WarmBrain()

    async def run():
        await orch._pipeline_text("통역 모드 켜줘")
        if orch._warm_task is not None:
            await orch._warm_task
    asyncio.run(run())
    assert warmed == [True]
```

- [ ] **Step 2: Run** `-k warms` — FAIL(AttributeError `_warm_task`).

- [ ] **Step 3: Implement** — `jarvis/core/orchestrator.py`:

(a) `__init__`에 `self._warm_task: asyncio.Task | None = None` 추가.

(b) `_toggle_interpret`의 `self.interpret_mode = (cmd == "on")` 직후에:

```python
        if self.interpret_mode and hasattr(self.brain, "warm_interpret"):
            # 안내 발화가 나가는 동안 백그라운드 예열 — 첫 통역 턴 콜드스타트 제거.
            self._warm_task = asyncio.create_task(self._warm_interpret_safe())
```

(c) `_toggle_interpret` 아래 새 메서드:

```python
    async def _warm_interpret_safe(self) -> None:
        try:
            await self.brain.warm_interpret()
        except Exception:  # noqa: BLE001 - 예열 실패는 무해
            pass
```

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_orchestrator.py -v` — all passed(`_XlateBrain`엔 warm_interpret이 없으므로 기존 통역 테스트는 hasattr 가드로 무영향).
- [ ] **Step 5: Commit** `git add jarvis/core/orchestrator.py tests/test_orchestrator.py && git commit -m "feat(튜닝): 통역 토글 on 시 백그라운드 번역 예열"`

---

### Task 5: ACK 필러 부팅 프리캐시

**Files:**
- Modify: `jarvis/core/orchestrator.py` — `_play_phrase`에서 합성부를 `_synth_phrase`로 분리 + `warm_phrases`
- Modify: `jarvis/__main__.py` — `await orch.brain.warm()` 다음 줄에 `await orch.warm_phrases()`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**:

```python
def test_warm_phrases_precaches_ack_and_greet():
    orch, _pb = _make()

    async def run():
        await orch.warm_phrases()
    asyncio.run(run())
    cached = set(orch._ack_cache)
    assert {en for en, _ in orch.ACK_FILLERS} <= cached
    assert "Yes, sir?" in cached
```

- [ ] **Step 2: Run** `-k warm_phrases` — FAIL(AttributeError).

- [ ] **Step 3: Implement** — `jarvis/core/orchestrator.py`의 `_play_phrase`를 다음으로 교체:

```python
    async def _synth_phrase(self, en: str) -> np.ndarray | None:
        out = self._ack_cache.get(en)
        if out is None:
            try:
                audio = await self.tts.synth(en)
                conv = await asyncio.to_thread(self.vc.convert, audio, self.tts.sample_rate)
                out = resample(np.asarray(conv, dtype=np.float32).reshape(-1),
                               self.vc.sample_rate, self.settings.playback_rate)
            except Exception:  # noqa: BLE001 - canned phrase is best-effort
                return None
            self._ack_cache[en] = out
        return out

    async def _play_phrase(self, en: str, ko: str) -> None:
        out = await self._synth_phrase(en)
        if out is None:
            return
        self._queue_audio(out, ko)

    async def warm_phrases(self) -> None:
        # 부팅 직후 호출 — 캔드 프레이즈를 미리 합성해 첫 ACK·인사도 0지연.
        for en, _ko in (*self.ACK_FILLERS, ("Yes, sir?", "네, 주인님?")):
            await self._synth_phrase(en)
```

그리고 `jarvis/__main__.py`의 `await orch.brain.warm()` 다음 줄에 `await orch.warm_phrases()` 추가(같은 들여쓰기).

- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/test_orchestrator.py tests/test_main_wiring.py -v` — all passed.
- [ ] **Step 5: Commit** `git add jarvis/core/orchestrator.py jarvis/__main__.py tests/test_orchestrator.py && git commit -m "feat(튜닝): ACK 필러·인사 부팅 프리캐시 — 첫 응대 합성 지연 제거"`

---

### Task 6: 전체 검증

- [ ] `.venv/bin/python -m pytest` — 전부 통과(376+신규).
- [ ] `.venv/bin/python -c "import jarvis.__main__"` — import 무결.
- [ ] 수정 있었으면 커밋.
