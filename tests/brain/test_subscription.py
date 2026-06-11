import asyncio
import types

from jarvis.brain.subscription import _GUIDANCE, _GUIDANCE_EN, _GUIDANCE_KO, SubscriptionBrain, _strip_sources


class FakeText:
    def __init__(self, t): self.text = t


class FakeAssistant:
    def __init__(self, *texts): self.content = [FakeText(t) for t in texts]


class FakeStreamEvent:
    def __init__(self, text=None, type_="content_block_delta"):
        self.event = ({"type": type_, "delta": {"type": "text_delta", "text": text}}
                      if text is not None else {"type": type_})


class FakeToolStart(FakeStreamEvent):
    def __init__(self, kind="tool_use"):
        self.event = {"type": "content_block_start", "content_block": {"type": kind}}


class FakeOther:
    pass


class FakeOptions:
    def __init__(self, **kw): self.kw = kw


class FakeClient:
    instances = 0

    def __init__(self, options=None):
        FakeClient.instances += 1
        self.options = options
        self.connected = False
        self.queries = []
        self.script = []  # messages to emit per receive_response

    async def connect(self):
        self.connected = True

    async def query(self, prompt, session_id="default"):
        self.queries.append(prompt)

    async def receive_response(self):
        for m in self.script:
            yield m

    async def disconnect(self):
        self.connected = False


def _brain(settings=None):
    FakeClient.instances = 0
    return SubscriptionBrain(
        settings or types.SimpleNamespace(subscription_model=""),
        types.SimpleNamespace(text=lambda: "사용자 이름은 이성재."),
        "PERSONA가" * 10,
        client_cls=FakeClient,
        options_cls=FakeOptions,
        assistant_message=FakeAssistant,
        stream_event=FakeStreamEvent,
    )


async def _talk(brain, script, text="안녕"):
    client = await brain._ensure_client()
    client.script = script
    return [d async for d in brain.respond(text)], client


def test_streams_partial_deltas_and_skips_final_duplicate():
    async def run():
        b = _brain()
        out, client = await _talk(b, [
            FakeOther(),
            FakeStreamEvent("안녕"),
            FakeStreamEvent("하세요"),
            FakeAssistant("안녕하세요"),   # full text repeats — must NOT double-yield
        ])
        # marker-buffering may re-chunk, but the spoken text concatenation is exact
        assert "".join(out) == "안녕하세요"
        assert client.queries == ["안녕"]
    asyncio.run(run())


def test_tool_use_emits_filler_before_search_then_answer():
    async def run():
        b = _brain()
        out, _ = await _talk(b, [
            FakeToolStart("server_tool_use"),   # web search begins
            FakeStreamEvent("최근 결과는"),       # answer streams after
            FakeStreamEvent(" 이렇습니다."),
        ])
        assert out[0] == SubscriptionBrain.TOOL_FILLER  # immediate spoken ack
        assert "".join(out[1:]) == "최근 결과는 이렇습니다."
    asyncio.run(run())


def test_ko_marker_splits_speech_and_subtitle():
    async def run():
        b = _brain()
        out, _ = await _talk(b, [
            FakeStreamEvent("Good evening, sir."),
            FakeStreamEvent(" [KO] 안녕하세요, "),
            FakeStreamEvent("성재님."),
        ])
        spoken = "".join(out)
        assert "Good evening, sir." in spoken and "[KO]" not in spoken and "안녕" not in spoken
        assert b.last_subtitle == "안녕하세요, 성재님."
    asyncio.run(run())


def test_deep_trigger_switches_to_deep_model_and_thinking():
    async def run():
        s = types.SimpleNamespace(subscription_model="claude-sonnet-4-6",
                                  deep_model="claude-opus-4-8")
        b = _brain(s)
        assert b._turn_config("안녕") == ("claude-sonnet-4-6", 0)
        assert b._turn_config("최대 사고로 진행해") == ("claude-opus-4-8", 12000)
        await _talk(b, [FakeAssistant("a")])      # normal -> sonnet, thinking 0
        assert FakeClient.instances == 1
        model, thinking = b._turn_config("최대 사고로 진행해 줘")
        c = await b._ensure_client(thinking, model)
        assert FakeClient.instances == 2          # reconnected (opus + thinking)
        assert c.options.kw["max_thinking_tokens"] == 12000
        assert c.options.kw["model"] == "claude-opus-4-8"
    asyncio.run(run())


def test_subtitle_strips_sources_and_urls():
    cleaned = _strip_sources("서울은 맑습니다 (출처: weather.com) https://x.com/y 입니다 [3]")
    assert "http" not in cleaned and "출처" not in cleaned and "[3]" not in cleaned
    assert "서울은 맑습니다" in cleaned


def test_no_filler_when_no_tool_used():
    async def run():
        b = _brain()
        out, _ = await _talk(b, [FakeStreamEvent("안녕하세요")])
        assert SubscriptionBrain.TOOL_FILLER not in out
    asyncio.run(run())


def test_falls_back_to_assistant_message_without_partials():
    async def run():
        b = _brain()
        out, _ = await _talk(b, [FakeOther(), FakeAssistant("전체 답변")])
        assert out == ["전체 답변"]
    asyncio.run(run())


def test_client_is_persistent_across_turns():
    async def run():
        b = _brain()
        await _talk(b, [FakeAssistant("a")])
        await _talk(b, [FakeAssistant("b")])
        assert FakeClient.instances == 1  # no per-turn CLI cold start
    asyncio.run(run())


def test_options_isolated_streaming_and_key_stripped(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-leak")
    async def run():
        b = _brain()
        client = await b._ensure_client()
        kw = client.options.kw
        assert "WebSearch" in kw["allowed_tools"]
        assert "mcp__jarvis__open_app" in kw["allowed_tools"]
        assert "jarvis" in kw["mcp_servers"]
        # 풀 도구 개방 — disallowed_tools 삭제, can_use_tool 콜백이 음성 게이트 역할.
        assert "disallowed_tools" not in kw
        assert callable(kw["can_use_tool"])
        assert kw["setting_sources"] == [] and kw["include_partial_messages"] is True
        assert "ANTHROPIC_API_KEY" not in kw["env"]
    asyncio.run(run())


def test_system_prompt_has_persona_memory_guidance():
    sp = _brain()._system_prompt()
    assert "PERSONA" in sp and "이성재" in sp and _GUIDANCE in sp


def test_english_reply_language_uses_english_guidance():
    b = _brain(types.SimpleNamespace(subscription_model="", reply_language="en"))
    sp = b._system_prompt()
    assert "reply in ENGLISH" in sp and "sir" in sp
    assert b._tool_filler() == SubscriptionBrain.TOOL_FILLER_EN


def test_korean_reply_language_default():
    b = _brain()  # no reply_language -> Korean
    assert "한국어" in b._system_prompt()
    assert b._tool_filler() == SubscriptionBrain.TOOL_FILLER


def test_warm_connects():
    async def run():
        b = _brain()
        await b.warm()
        assert b._client is not None and b._client.connected
        await b.close()
        assert b._client is None
    asyncio.run(run())


def test_subscription_model_passed_when_set():
    async def run():
        b = _brain(types.SimpleNamespace(subscription_model="claude-opus-4-8"))
        client = await b._ensure_client()
        assert client.options.kw["model"] == "claude-opus-4-8"
    asyncio.run(run())


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
            self.disconnects = getattr(self, "disconnects", 0) + 1

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
    assert all(getattr(c, "disconnects", 0) == 1 for c in instances)


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


def test_guidance_mentions_screen_tools():
    for g in (_GUIDANCE_EN, _GUIDANCE_KO):
        assert "capture_screen" in g
        assert "screen_control" in g


def test_translate_concurrent_same_direction_serialized():
    """예열과 첫 통역이 같은 방향을 동시에 때려도 클라이언트 1개·응답 혼선 없음(락)."""
    import asyncio

    from jarvis.brain.subscription import SubscriptionBrain
    from jarvis.core.config import Settings

    instances = []

    class _FakeOptions:
        def __init__(self, **kw):
            pass

    class _SlowClient:
        def __init__(self, options=None):
            instances.append(self)
            self.active = 0

        async def connect(self):
            await asyncio.sleep(0)

        async def disconnect(self):
            pass

        async def query(self, text):
            self._text = text

        async def receive_response(self):
            self.active += 1
            assert self.active == 1, "동시 receive_response — 응답 훔치기 레이스"
            await asyncio.sleep(0)

            class _Blk:
                type = "text"
                text = ""
            _Blk.text = f"<{self._text}>"

            class _Msg:
                content = [_Blk()]
            yield _Msg()
            self.active -= 1

    brain = SubscriptionBrain(Settings(), None, "p" * 4096,
                              client_cls=_SlowClient, options_cls=_FakeOptions)

    async def run():
        return await asyncio.gather(
            brain.translate("hi", "Korean"),
            brain.translate("진짜 질문", "Korean"),
        )

    a, b = asyncio.run(run())
    assert len(instances) == 1          # 더블 커넥트 없음
    assert a == "<hi>" and b == "<진짜 질문>"  # 각자 자기 응답


def test_translate_cancellation_evicts_cached_client():
    """바지인 취소가 반쯤 소비된 세션을 캐시에 남기지 않는다."""
    import asyncio

    from jarvis.brain.subscription import SubscriptionBrain
    from jarvis.core.config import Settings

    disconnected = []

    class _FakeOptions:
        def __init__(self, **kw):
            pass

    class _HangClient:
        def __init__(self, options=None):
            pass

        async def connect(self):
            pass

        async def disconnect(self):
            disconnected.append(True)

        async def query(self, text):
            pass

        async def receive_response(self):
            await asyncio.Event().wait()  # 영원히 스트리밍 중
            yield  # pragma: no cover

    brain = SubscriptionBrain(Settings(), None, "p" * 4096,
                              client_cls=_HangClient, options_cls=_FakeOptions)

    async def run():
        task = asyncio.create_task(brain.translate("안녕", "English"))
        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert brain._xlate == {}  # 오염된 세션 폐기
        await asyncio.sleep(0.01)  # 백그라운드 disconnect 완료 여유

    asyncio.run(run())
    assert disconnected == [True]
