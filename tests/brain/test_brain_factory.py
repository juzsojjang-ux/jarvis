import types

import pytest

from jarvis.brain.claude import Brain
from jarvis.brain.factory import make_brain
from jarvis.brain.subscription import SubscriptionBrain


def _mem():
    return types.SimpleNamespace(text=lambda: "")


def test_default_is_subscription():
    s = types.SimpleNamespace(brain_backend="subscription", subscription_model="")
    assert isinstance(make_brain(s, _mem(), "P"), SubscriptionBrain)


def test_api_backend_builds_brain_without_keyring():
    # client is injected (truthy) so Brain never constructs AsyncAnthropic / reads keyring
    s = types.SimpleNamespace(brain_backend="api", model_task="m", model_conversational="m")
    assert isinstance(make_brain(s, _mem(), "P", client=object()), Brain)


def test_unknown_backend_raises():
    s = types.SimpleNamespace(brain_backend="bogus")
    with pytest.raises(ValueError):
        make_brain(s, _mem(), "P")
