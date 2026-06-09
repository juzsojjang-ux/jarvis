"""JARVIS heads-up display: a movie-style voice-reactive orb (Avengers JARVIS look).

A dependency-free localhost HTTP/SSE server (orb_server.OrbServer) serves orb.html and
streams {state, level} events the orchestrator publishes on each state change. The orb
(WebGL, three.js) reacts: idle breathing, listening ripple, thinking swirl, speaking
turbulence scaled by voice amplitude.
"""
from jarvis.hud.level import audio_level
from jarvis.hud.orb_server import OrbHub, OrbServer

__all__ = ["OrbServer", "OrbHub", "audio_level"]
