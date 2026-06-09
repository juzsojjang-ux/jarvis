"""Config-driven brain backend selection.

"subscription" (default): Claude Pro/Max login via claude-agent-sdk — NO API key, no
per-token bill. "api": the original Anthropic-API Brain (tools + routing) for users who
prefer pay-per-token or need the full local tool loop.
"""
from __future__ import annotations

from typing import Any


def make_brain(
    settings: Any,
    memory: Any,
    persona_text: str,
    *,
    client: Any = None,
    registry: Any = None,
    confirm: Any = None,
) -> Any:
    backend = getattr(settings, "brain_backend", "subscription")
    if backend == "subscription":
        from jarvis.brain.subscription import SubscriptionBrain
        return SubscriptionBrain(settings, memory, persona_text)
    if backend == "api":
        from jarvis.brain.claude import Brain
        return Brain(settings, memory, persona_text, client=client,
                     registry=registry, confirm=confirm)
    raise ValueError(f"unknown brain_backend: {backend!r}")
