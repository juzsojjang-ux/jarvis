from pathlib import Path

# Persona must exceed the 4096-token cache minimum (Opus 4.8 / Haiku 4.5) so the
# system prefix is cacheable. ~7000 Korean chars is a safe proxy.
MIN_CHARS = 7000


def load_persona(path: Path) -> str:
    text = Path(path).read_text(encoding="utf-8")
    if len(text) < MIN_CHARS:
        raise ValueError(
            f"persona too short ({len(text)} chars); needs >= {MIN_CHARS} to exceed the "
            "4096-token prompt-cache minimum"
        )
    return text
