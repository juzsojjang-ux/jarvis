from jarvis.brain.base import BRAIN_PROVIDERS, Brain, split_ko


def test_providers_constant():
    assert BRAIN_PROVIDERS == ("claude", "gemini", "gpt")


def test_split_ko_with_marker():
    en, ko = split_ko("Hello, sir.[KO] 안녕하세요, 주인님.")
    assert en == "Hello, sir."
    assert ko == "안녕하세요, 주인님."


def test_split_ko_no_marker():
    en, ko = split_ko("Just English, sir.")
    assert en == "Just English, sir."
    assert ko == ""


def test_split_ko_strips_and_handles_first_marker_only():
    en, ko = split_ko("A[KO] 가[KO] 나")
    assert en == "A"
    assert ko == "가[KO] 나"  # only the first marker splits


def test_subscription_brain_satisfies_protocol():
    from jarvis.brain.subscription import SubscriptionBrain
    import types as _t
    b = SubscriptionBrain(_t.SimpleNamespace(subscription_model=""), None, "p" * 4096)
    assert isinstance(b, Brain)
