from __future__ import annotations

import asyncio
import os

from anthropic import AsyncAnthropic

from .activation.ptt import PushToTalk
from .audio.capture import MicCapture
from .audio.playback import Playback
from .brain.claude import Brain
from .brain.memory import MemoryStore
from .brain.persona import load_persona
from .brain.sentence import SentenceChunker
from .core.config import Settings
from .core.orchestrator import Orchestrator
from .stt.mlx_whisper import MLXWhisperSTT
from .tts.system_say import SystemSayTTS
from .vc.null_vc import NullVC


def build_orchestrator(*, client: AsyncAnthropic | None = None) -> Orchestrator:
    settings = Settings()
    memory = MemoryStore(settings.memory_path)
    memory.load()
    persona = load_persona(settings.persona_path)
    brain = Brain(settings, memory, persona, client=client)
    return Orchestrator(
        settings=settings,
        activator=PushToTalk(settings.ptt_key),
        capture=MicCapture(sample_rate=16000),
        stt=MLXWhisperSTT(settings.stt_repo, language=settings.language),
        brain=brain,
        chunker=SentenceChunker(),
        tts=SystemSayTTS(voice="Yuna"),
        vc=NullVC(sample_rate=settings.playback_rate),
        playback=Playback(sample_rate=settings.playback_rate),
    )


async def _amain() -> None:
    orch = build_orchestrator()
    # Warm models + cache before listening.
    orch.stt.warm()
    orch.tts.warm()
    orch.vc.warm()
    await orch.brain.warm()
    print("자비스 준비 완료. 오른쪽 옵션 키를 누른 채 말씀하세요. (Ctrl+C로 종료)")
    await orch.run()


def main() -> None:
    # After the first model download, run with HF_HUB_OFFLINE=1 for fully local STT.
    os.environ.setdefault("HF_HUB_OFFLINE", os.environ.get("HF_HUB_OFFLINE", "0"))
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        print("\n종료합니다.")


if __name__ == "__main__":
    main()
