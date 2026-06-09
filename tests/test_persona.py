from jarvis.brain.persona import load_persona
from jarvis.core.config import Settings


def test_persona_loads_and_exceeds_cache_minimum():
    text = load_persona(Settings().persona_path)
    assert isinstance(text, str)
    # Must comfortably exceed the 4096-token cache minimum for Opus 4.8 / Haiku 4.5.
    # ~7000+ Korean chars safely clears 4096 tokens.
    assert len(text) >= 7000
    assert "자비스" in text  # JARVIS persona marker (Korean)


def test_short_persona_rejected(tmp_path):
    p = tmp_path / "short.md"
    p.write_text("너무 짧다", encoding="utf-8")
    raised = False
    try:
        load_persona(p)
    except ValueError:
        raised = True
    assert raised
