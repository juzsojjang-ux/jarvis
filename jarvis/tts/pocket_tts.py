"""Pocket-TTS backend (TTSBackend): the JARVIS voice via Kyutai Pocket TTS cloning —
the engine from the NetHyTech video. English-only, CPU real-time. Spawns the .venv-pocket
worker (jarvis.tts.pocket_worker) and exchanges float32 PCM over jarvis.tts.ipc. 24000 Hz.

Reuses MeloTTSKR's proc/warm/synth/close plumbing (identical IPC contract); only the
launch command and the worker env (reference path) differ.
"""
from __future__ import annotations

import asyncio
import os
import sys

from jarvis.tts.melotts_kr import MeloTTSKR


class PocketTTS(MeloTTSKR):
    sample_rate: int = 24000

    def __init__(self, worker_cmd: list[str] | None = None, *, ref_path: str | None = None,
                 repo_root: str | None = None, hf_home: str | None = None):
        # NOTE: intentionally NOT calling super().__init__ (it wires the MeloTTS cmd).
        self.sample_rate = 24000
        self._cmd = worker_cmd or [
            os.path.expanduser("~/jarvis/.venv-pocket/bin/python"),
            "-m", "jarvis.tts.pocket_worker",
        ]
        env = {**os.environ}
        # frozen 번들: 워커는 같은 번들 인터프리터(--child=)로 떠 jarvis가 이미 번들 아카이브에
        # 있다. 소스 repo PYTHONPATH를 걸면 stale/충돌 import가 되므로 걸지 않는다.
        # dev: 워커가 별도 .venv-pocket이라 소스 jarvis를 import하도록 PYTHONPATH 주입.
        if getattr(sys, "frozen", False):
            self._repo_root = None
        else:
            self._repo_root = os.path.expanduser(repo_root or "~/jarvis")
            env["PYTHONPATH"] = self._repo_root
        if ref_path:
            env["JARVIS_POCKET_REF"] = os.path.expanduser(ref_path)
        # 배포 설치본: 게이트된 음색 가중치를 토큰 없이 오프라인 로드. HF_HOME/오프라인을
        # 워커 *프로세스 env에만* 건다(전역에 걸면 Whisper STT 첫 다운로드가 막힌다).
        if hf_home:
            env["HF_HOME"] = os.path.expanduser(hf_home)
            env["HF_HUB_OFFLINE"] = "1"
            env["TRANSFORMERS_OFFLINE"] = "1"
        self._env = env
        self._proc = None
        self._lock = asyncio.Lock()
