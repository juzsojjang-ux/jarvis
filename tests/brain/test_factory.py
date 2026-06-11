import types

import pytest
from jarvis.brain.factory import make_brain


def _settings(**kw):
    base = dict(brain_provider="claude", brain_backend="subscription", subscription_model="")
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_factory_claude_subscription():
    from jarvis.brain.subscription import SubscriptionBrain
    b = make_brain(_settings(), None, "p" * 4096)
    assert isinstance(b, SubscriptionBrain)


def test_factory_default_provider_is_claude(monkeypatch):
    # provider attr missing → treated as claude
    s = types.SimpleNamespace(brain_backend="subscription", subscription_model="")
    from jarvis.brain.subscription import SubscriptionBrain
    assert isinstance(make_brain(s, None, "p" * 4096), SubscriptionBrain)


def test_factory_gemini_builds_brain():
    from jarvis.brain.gemini import GeminiBrain
    b = make_brain(_settings(brain_provider="gemini", gemini_model="gemini-2.5-flash"),
                   None, "p" * 4096)
    assert isinstance(b, GeminiBrain)


def test_factory_gpt_builds_brain():
    from jarvis.brain.openai_brain import GPTBrain
    b = make_brain(_settings(brain_provider="gpt", gpt_model="gpt-4o"),
                   None, "p" * 4096)
    assert isinstance(b, GPTBrain)


def test_factory_unknown_provider():
    with pytest.raises(ValueError):
        make_brain(_settings(brain_provider="llama"), None, "p" * 4096)
