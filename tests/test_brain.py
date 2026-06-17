import asyncio
from types import SimpleNamespace

from jarvis.brain.claude import Brain
from jarvis.core.config import Settings


class _FakeStream:
    def __init__(self, deltas, usage):
        self._deltas = deltas
        self._usage = usage

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def text_stream(self):
        async def gen():
            for d in self._deltas:
                yield d
        return gen()

    async def get_final_message(self):
        return SimpleNamespace(usage=self._usage)


class _FakeMessages:
    def __init__(self):
        self.stream_kwargs = None
        self.create_kwargs = None

    def stream(self, **kwargs):
        self.stream_kwargs = kwargs
        return _FakeStream(["안녕하", "세요. 무엇을 ", "도와드릴까요?"],
                           SimpleNamespace(cache_read_input_tokens=4321))

    async def create(self, **kwargs):
        self.create_kwargs = kwargs
        return SimpleNamespace(usage=SimpleNamespace(cache_creation_input_tokens=4096))


class _FakeAnthropic:
    def __init__(self):
        self.messages = _FakeMessages()


class _Mem:
    def text(self):
        return "- 사용자 이름은 이성재"


def _make_brain():
    fake = _FakeAnthropic()
    persona = "가" * 7000  # stands in for the cached persona prefix
    return Brain(Settings(), _Mem(), persona, client=fake), fake


def test_respond_streams_deltas_with_cached_persona():
    brain, fake = _make_brain()

    async def run():
        out = []
        async for d in brain.respond("안녕"):
            out.append(d)
        return out

    out = asyncio.run(run())
    assert "".join(out) == "안녕하세요. 무엇을 도와드릴까요?"

    kw = fake.messages.stream_kwargs
    assert kw["model"] == "claude-haiku-4-5"
    # System: [cached persona block, uncached memory+guidance block]
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["system"][0]["text"] == "가" * 7000
    assert "이성재" in kw["system"][1]["text"]
    assert "최종" in kw["system"][1]["text"]  # final-answer-only instruction present
    # No effort / thinking on the Haiku path.
    assert "output_config" not in kw
    assert "thinking" not in kw
    assert brain.last_usage.cache_read_input_tokens == 4321


def test_warm_prewarms_with_min_tokens():
    # max_tokens는 1 이상이어야 Anthropic API가 수락한다(0이면 400) — 예열은 max_tokens=1.
    brain, fake = _make_brain()
    asyncio.run(brain.warm())
    ck = fake.messages.create_kwargs
    assert ck["max_tokens"] == 1
    assert ck["model"] == "claude-haiku-4-5"
    assert ck["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert ck["system"][0]["text"] == "가" * 7000  # same prefix bytes as respond()
