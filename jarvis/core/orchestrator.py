from __future__ import annotations

import asyncio
import contextlib
import re
import sys

import numpy as np

from ..audio.util import resample
from ..audio.wake import match_wake
from ..brain.usage import UsageTracker, is_limit_error
from ..hud import notice_bus
from ..hud.telemetry import TelemetryProvider
from ..hud.level import audio_level, chunk_levels
from .control_gate import CONTROL_GATE, TRUST_GATE
from .events import State
from .interpret import detect_lang, interpret_speak_korean

_HUD_HOP_S = 0.1  # orb level update cadence (10 Hz)


def format_latency(stt_s: float | None, first_s: float) -> str:
    """튜닝용 한 줄 지연 로그 — 측정 없이는 반복(로드맵 4단계) 불가."""
    if stt_s is None:
        return f"[지연] 두뇌 첫문장 {first_s:.2f}s"
    return (f"[지연] STT {stt_s:.2f}s · 두뇌 첫문장 {first_s:.2f}s"
            f" · 합계 {stt_s + first_s:.2f}s")


class Orchestrator:
    """Wires Activator -> capture -> STT -> Brain -> SentenceChunker -> TTS -> VC ->
    playback. Barge-in cancels the in-flight Brain pipeline Task (CancelledError
    suppressed) and aborts playback. ``hud`` (optional OrbServer) receives best-effort
    {state, level} publishes so the on-screen orb reacts to the conversation."""

    def __init__(self, *, settings, activator, capture, stt, brain, chunker, tts, vc,
                 playback, hud=None, micstream=None, wake=None):
        self.settings = settings
        self.activator = activator
        self.capture = capture
        self.stt = stt
        self.brain = brain
        self.chunker = chunker
        self.tts = tts
        self.vc = vc
        self.playback = playback
        self.hud = hud
        self.micstream = micstream
        self.wake = wake
        self.proactive = None  # ProactiveEngine — 배선(__main__)에서 주입, run()이 시작
        self.interpret_mode = False  # "통역 모드" — 두뇌 우회, 한↔영 통역만
        self.state = State.IDLE
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._bg_tasks: set[asyncio.Task] = set()
        self._mic_meter: asyncio.Task | None = None
        # Instant acknowledgement spoken the moment you finish — then JARVIS thinks.
        self._ack_i = 0
        self._ack_cache: dict[str, np.ndarray] = {}
        # 연속대화: 답변 직후 이 시각까지는 웨이크워드 없이 follow-up을 받는다.
        self._follow_up_until = 0.0
        # "자비스"만 부른 뒤 3초 듣는 창이 정적으로 끝나면 그제야 "네 주인님?" 인사할지.
        self._greet_if_idle = False
        # 에코 쿨다운: 자비스 발화 직후 잔향을 자기 목소리로 오인하지 않도록.
        self._wake_blocked_until = 0.0
        self._last_stt_s: float | None = None
        # Speaking levels queue: _speak pushes per-hop levels; the pump publishes
        # them at playback cadence so the orb moves WITH the audio.
        self._spk_levels: asyncio.Queue[float] = asyncio.Queue()
        self._spk_pump: asyncio.Task | None = None
        self._attentive_timer: asyncio.Task | None = None
        self._warm_task: asyncio.Task | None = None
        self._remote_busy = False
        self._watch_task = None  # 화면 감시 모드 루프
        self.usage = UsageTracker()  # 토큰 사용량 집계(세션+누적)
        self.last_bug: str | None = None  # 마지막 오류 상세 — "고쳐줘" 참조 + 우측 알림
        self._panel_muted = False
        self._ack_delay_s = 0.9  # 이 시간 안에 두뇌 첫 문장이 오면 "잠시만요" 필러 생략
        # 두뇌의 show_panel/hide_panel 도구가 이 HUD에 닿도록 알림 싱크를 건다.
        notice_bus.set_sink(self._panel_sink)
        # HUD 실시간 텔레메트리 공급자 — hub가 있을 때만(테스트/HUD 비활성 시 생략).
        # 데몬 스레드라 프로세스 종료 시 자동 정리(별도 stop 불필요).
        self._telemetry = None
        _hub = getattr(self.hud, "hub", None)
        if _hub is not None:
            self._telemetry = TelemetryProvider(_hub, state_fn=self._telemetry_state)
            self._telemetry.start()

    # ----- PTT callbacks (invoked from the pynput listener thread) -----
    def _press(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._on_press)

    def _release(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._on_release)

    def _on_press(self) -> None:
        if self._remote_busy:
            return  # 원격 턴 진행 중 — PTT 무시(상태·캡처를 건드리면 게이트가 풀린다)
        # Barge-in: a press while a pipeline is running cancels it before re-capturing.
        if self._task is not None and not self._task.done():
            # Keep a strong ref: the loop only weakly references tasks, so a bare
            # create_task() can be GC'd mid-await and silently skip playback.abort().
            bg = asyncio.create_task(self._cancel_pipeline())
            self._bg_tasks.add(bg)
            bg.add_done_callback(self._bg_tasks.discard)
        self.state = State.CAPTURING
        self.capture.start()
        self._publish("listening")
        if self._mic_meter is None or self._mic_meter.done():
            self._mic_meter = asyncio.create_task(self._mic_meter_loop())

    def _on_release(self) -> None:
        if self._mic_meter is not None:
            self._mic_meter.cancel()
            self._mic_meter = None
        pcm = self.capture.stop()
        if self.wake is None and self.micstream is not None:
            # PTT 전용 모드: 누르는 동안만 마이크 점등(상시-온은 웨이크 모드 전용).
            self.micstream.stop()
        if self._remote_busy:
            self._to_idle()  # 원격 턴 진행 중 — PTT 발화 폐기(두뇌 동시 사용 방지)
            return
        self.state = State.TRANSCRIBING
        self._task = asyncio.create_task(self._pipeline(pcm))

    async def _mic_meter_loop(self) -> None:
        # Live input meter: the orb pulses with the USER's voice while the key is held.
        with contextlib.suppress(asyncio.CancelledError):
            while self.state == State.CAPTURING:
                tail = self.capture.level_tail()
                self._publish("listening", audio_level(tail))
                await asyncio.sleep(_HUD_HOP_S)

    def _publish(self, state: str, level: float = 0.0, text: str | None = None) -> None:
        # Best-effort: the orb HUD must never break the voice pipeline.
        if self.hud is not None:
            try:
                self.hud.publish(state, level, text)
            except Exception:
                pass

    def _notify(self, msg: str) -> None:
        """우측 상단 알림 카드 갱신(오류/한도 같은 시스템 알림). 빈 문자열이면 끈다.
        사용자가 "패널 꺼"로 음소거했으면 새 시스템 알림은 억제한다."""
        if self._panel_muted and msg:
            return
        if self.hud is not None:
            try:
                self.hud.publish_notice(msg)
            except Exception:  # noqa: BLE001
                pass

    def _telemetry_state(self) -> dict:
        """텔레메트리 공급자에 넘길 실시간 상태(진짜 데이터). 예외는 공급자가 삼킨다."""
        return {
            "mic_on": self.state == State.CAPTURING,
            "task_count": len(self._bg_tasks),
            "net": None,  # 네트워크 표시는 후속(현재 생략 — 가짜 데이터 금지)
        }

    def _panel_sink(self, msg: str) -> None:
        """두뇌의 show_panel/hide_panel 경유 표시 — 사용자가 두뇌에게 직접 요청한
        것이므로, 이전에 "패널 꺼"로 음소거했어도 표시 요청은 음소거를 푼다."""
        if msg:
            self._panel_muted = False
        if self.hud is not None:
            try:
                self.hud.publish_notice(msg)
            except Exception:  # noqa: BLE001
                pass

    async def _await_warm(self) -> None:
        """부팅 시 백그라운드로 시작한 두뇌 예열을 첫 턴이 1회 대기한다(이후엔 즉시 통과).
        예열 throwaway 쿼리가 실제 쿼리와 겹치지 않게 하고, 첫 턴이 예열된 클라이언트를
        그대로 쓰게 한다. 예열 실패는 삼킨다 — 실제 턴에서 같은 오류가 나면 그때 알린다."""
        t = self._warm_task
        if t is None:
            return
        # done이면 await가 즉시 반환(예외였으면 회수해 삼킴), 미완료면 대기.
        with contextlib.suppress(Exception):
            await t

    def _to_idle(self) -> None:
        # 상태 복귀와 HUD publish는 반드시 한 쌍이다 — 따로 쓰다 한쪽을 빼먹으면
        # 오브가 PROCESSING에 갇힌다(실제로 났던 버그). IDLE 복귀는 전부 여기로.
        self.state = State.IDLE
        self._publish("idle")

    # ----- pipeline -----
    async def _cancel_pipeline(self) -> None:
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._drain_levels()  # stop the orb animating speech that was just cancelled
        if self._spk_pump is not None and not self._spk_pump.done():
            self._spk_pump.cancel()
        self.playback.abort()
        # State transitions are owned by _on_press/_on_release; do NOT set IDLE here —
        # during a barge-in this runs after _on_press already set CAPTURING.

    async def _pipeline(self, pcm: np.ndarray) -> None:
        try:
            lang = None if self.interpret_mode else self.settings.language
            t0 = asyncio.get_running_loop().time()
            text = await asyncio.to_thread(self.stt.transcribe, pcm, 16000, lang)
            self._last_stt_s = asyncio.get_running_loop().time() - t0
            await self._pipeline_text(text)
        except Exception as exc:  # noqa: BLE001 - 한 턴의 실패가 상태를 가두면 안 된다
            await self._announce_error(exc)

    async def _pipeline_text(self, text: str, *, ack: bool = True) -> None:
        if not text.strip():
            self._to_idle()
            return
        ctl = self._control_command(text)
        if ctl is not None:
            await self._toggle_control(ctl)
            return
        trust = self._trust_command(text)
        if trust is not None:
            await self._toggle_trust(trust)
            return
        cmd = self._interpret_command(text)
        if cmd is not None:
            await self._toggle_interpret(cmd)
            return
        if self._usage_command(text):
            await self._report_usage()
            return
        if self._selfcheck_command(text):
            await self._run_selfcheck()
            return
        wcmd = self._watch_command(text)
        if wcmd is not None:
            await self._toggle_watch(wcmd)
            return
        pcmd = self._panel_command(text)
        if pcmd is not None:
            await self._toggle_panel(pcmd)
            return
        ex = self._expand_command(text)
        if ex is not None:
            if self.hud is not None:
                try:
                    cur = self.state.name.lower()
                except Exception:
                    cur = "idle"
                try:
                    self.hud.publish(cur, 0.0, expand=ex)
                except Exception:
                    pass
            await self._play_phrase("Very well, sir.",
                                    "크게 띄웠습니다." if ex else "작게 했습니다.")
            self._to_idle()
            return
        if self.interpret_mode:
            await self._interpret_turn(text)
            return
        self.state = State.THINKING
        self._publish("thinking")
        text = self._watch_context() + text
        t_think = asyncio.get_running_loop().time()
        first_done = False

        def _mark_first() -> None:
            nonlocal first_done
            if first_done:
                return
            first_done = True
            try:
                dt = asyncio.get_running_loop().time() - t_think
                print(format_latency(self._last_stt_s, dt))
            except Exception:  # noqa: BLE001 - 계측이 턴을 깨면 안 된다
                pass
            self._last_stt_s = None

        # 필러("잠시만 기다려주세요")는 빠른 답엔 내보내지 않는다 — 두뇌가 실제로 늦을
        # 때(도구 실행·긴 생각)만. 0.9초 안에 첫 문장이 오면 first_done이 서서 건너뛴다.
        ack_task = None
        if ack:
            async def _delayed_ack() -> None:
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.sleep(self._ack_delay_s)
                    if first_done:
                        return
                    en, ko = self.ACK_FILLERS[self._ack_i % len(self.ACK_FILLERS)]
                    self._ack_i += 1
                    out = await self._synth_phrase(en)
                    # 합성하는 사이 첫 문장이 도착했으면 버린다 — 답변 뒤에 "잠시만요"가
                    # 따라붙는 역전 재생을 막는다.
                    if out is not None and not first_done:
                        self._queue_audio(out, ko)
            ack_task = asyncio.create_task(_delayed_ack())
        # 두뇌 스트림 읽기(producer)와 합성·재생(consumer)을 분리한다. producer가 LLM
        # 토큰을 앞서 읽어 문장을 큐에 쌓아두므로, LLM이 잠깐 끊겨도 합성이 굶지 않아
        # 문장 사이 무음 끊김이 사라진다(끊김 방지). consumer는 재생 속도로 합성한다.
        synth_q: asyncio.Queue = asyncio.Queue(maxsize=128)
        prod_err: dict = {"exc": None}

        async def _produce() -> None:
            try:
                await self._await_warm()  # 첫 턴: 백그라운드 두뇌 예열 완료까지 대기(필러가 공백 덮음)
                async for delta in self.brain.respond(text):
                    for sentence in self.chunker.feed(delta):
                        await synth_q.put(sentence)
                tail = self.chunker.flush()
                if tail:
                    await synth_q.put(tail)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - 한도 초과 등은 아래에서 알린다
                prod_err["exc"] = exc
            finally:
                await synth_q.put(None)  # 종료 신호(sentinel)

        producer = asyncio.create_task(_produce())
        spoken_parts: list[str] = []
        try:
            while True:
                sentence = await synth_q.get()
                if sentence is None:
                    break
                _mark_first()
                spoken_parts.append(sentence)
                # 발화 중엔 영어 자막을 띄우지 않는다(영어 자막 방지). 한국어 자막은
                # 아래 _finish_speaking에서 짧게 끊어 순차로 보여준다.
                await self._speak(sentence)
        finally:
            if not producer.done():
                producer.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await producer
            if ack_task is not None and not ack_task.done():
                ack_task.cancel()  # 아주 빠른 답: 아직 자던 필러를 취소(뒤늦게 안 나오게)
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await ack_task
        # 마지막 자막: 두뇌가 붙인 한국어 번역([KO])을 우선. 그게 비었으면(두뇌가 번역을
        # 빼먹은 경우) 말한 내용을 한국어로 번역해 채운다 — '번역 안 된 영어 자막'을 막는다.
        subtitle = await self._korean_subtitle(spoken_parts)
        await self._finish_speaking(subtitle)
        # 이번 턴 토큰 사용량 집계(있으면) — "사용량" 명령으로 조회한다.
        try:
            u = getattr(self.brain, "last_usage", None)
            if u is not None:
                self.usage.record(u)
        except Exception:  # noqa: BLE001 - 사용량 집계가 턴을 깨면 안 된다
            pass
        # 한도/요금 초과로 실패했으면 조용히 넘기지 말고 화면+음성으로 알린다.
        if getattr(self.brain, "last_error", None) == "limit" or is_limit_error(prod_err["exc"]):
            await self._announce_limit()
            return
        # 그 외 두뇌 오류(버그)도 삼키지 말고 알린다 — 사용자가 수정 요청할 수 있게.
        if prod_err["exc"] is not None:
            await self._announce_error(prod_err["exc"])
            return
        self.state = State.IDLE
        if self.wake is not None:
            self._enter_attentive()
        else:
            # PTT 전용 모드: follow-up을 들어줄 리스너가 없다 — '듣는 중' 표시와
            # 죽은 창을 열지 않는다.
            self._publish("idle")

    @staticmethod
    def _has_hangul(s: str) -> bool:
        return any("가" <= ch <= "힣" for ch in s)

    async def _korean_subtitle(self, spoken_parts: list[str]) -> str:
        """마무리 자막을 한국어로 보장한다. [KO] 번역이 있으면 그걸, 없으면 말한 내용을
        번역해서. 두 경로 다 실패하면 말한 그대로(자막이 비는 일은 없게)."""
        ko = (getattr(self.brain, "last_subtitle", "") or "").strip()
        if ko:
            return ko
        spoken = " ".join(p.strip() for p in spoken_parts if p.strip()).strip()
        if not spoken or self._has_hangul(spoken):
            return spoken  # 이미 한국어거나 말한 게 없음 — 번역 불필요
        # 번역 누락 → 말한 내용을 한국어 자막으로 번역(이 경우에만 추가 호출, 비용 최소)
        try:
            translated = await self.brain.translate(spoken, "ko")
            return (translated or "").strip() or spoken
        except Exception:  # noqa: BLE001 - 번역 실패해도 자막은 채운다
            return spoken

    @staticmethod
    def _split_subtitle(text: str, max_len: int = 26) -> list[str]:
        """긴 자막을 화면을 안 가리게 짧은 청크로 나눈다(문장→길면 공백/쉼표에서)."""
        text = (text or "").strip()
        if not text:
            return []
        parts = re.split(r"(?<=[.!?。…])\s+|\n+", text)
        chunks: list[str] = []
        for p in (s.strip() for s in parts if s and s.strip()):
            while len(p) > max_len:
                cut = max(p.rfind(" ", 0, max_len), p.rfind(",", 0, max_len),
                          p.rfind("·", 0, max_len), p.rfind("、", 0, max_len))
                if cut <= 0:
                    cut = max_len
                chunks.append(p[:cut].strip())
                p = p[cut:].strip()
            if p:
                chunks.append(p)
        return chunks

    def _subtitles_on(self) -> bool:
        # 한국어 모드(발화 자체가 한국어)면 자막은 중복 → 끈다(사용자 요구). 영어 모드는
        # 영어로 말하고 한국어 자막을 띄우므로 유용 → 유지.
        return not str(getattr(self.settings, "reply_language", "en")).lower().startswith("ko")

    async def _finish_speaking(self, subtitle: str) -> None:
        # 자막을 한 번에 다 띄우면 길어서 화면을 가린다 — 짧은 청크로 나눠, 남은
        # 오디오 길이에 맞춰 간격을 배분해 말하는 것과 같이 흘러가게 한다(동기).
        if not self._subtitles_on():
            subtitle = ""  # 한국어 모드: 자막 끔
        chunks = self._split_subtitle(subtitle)
        idx = 0
        if chunks:
            self._publish("speaking", 0.3, chunks[0])

        def _remaining_audio_s() -> float:
            pending = self.playback.pending() if hasattr(self.playback, "pending") else 0
            return max(0.0, float(pending) / float(self.settings.playback_rate or 48000))

        # 다음 청크로 넘어갈 시각: 남은오디오/남은청크 (1.0~3.0초로 클램프)
        def _next_interval() -> float:
            left = max(1, len(chunks) - 1 - idx)
            return min(3.0, max(1.0, _remaining_audio_s() / left)) if chunks else 1.6

        next_advance = _next_interval()
        elapsed = 0.0
        for _ in range(int(30 / _HUD_HOP_S)):  # cap ~30s safety
            pump_busy = self._spk_pump is not None and not self._spk_pump.done()
            pending = self.playback.pending() if hasattr(self.playback, "pending") else 0
            audio_done = not pump_busy and pending <= 0
            elapsed += _HUD_HOP_S
            if chunks and idx < len(chunks) - 1 and elapsed >= next_advance:
                idx += 1
                self._publish("speaking", 0.25, chunks[idx])
                elapsed = 0.0
                next_advance = _next_interval()
            if audio_done:
                break
            await asyncio.sleep(_HUD_HOP_S)
        # 오디오가 끝났는데 남은 청크가 있으면 마저 짧게 보여준다.
        while chunks and idx < len(chunks) - 1:
            idx += 1
            self._publish("speaking", 0.25, chunks[idx])
            await asyncio.sleep(0.8)

    # ----- wake word (영화식 호출: 키 없이 "자비스") -----
    def _wake_gate(self) -> bool:
        # WakeListener는 IDLE이고 에코 쿨다운이 지난 동안만 들을 수 있다.
        try:
            now = asyncio.get_running_loop().time()
        except RuntimeError:
            return False
        return (self.state == State.IDLE and now >= self._wake_blocked_until
                and not self._remote_busy)

    # 웨이크 판정엔 발화 앞부분만 변환한다 — 잡담 전체(최대 30초)를 위스퍼에
    # 태우는 게 상시 청취의 지배적 배터리 비용이라서다. 매칭이 확정된 뒤에만
    # 전체를 변환해 명령 전문을 얻는다.
    _WAKE_PREFIX_S = 4.0

    @staticmethod
    def _speech_start(arrived: float, n_samples: int, sample_rate: int = 16000) -> float:
        """발화가 '시작된' 대략 시각 = 도착(무음으로 종료 확정) 시각 − 캡처 길이.
        follow-up/3초 창 판정을 '말을 끝낸 시점'이 아니라 '말을 시작한 시점' 기준으로
        만든다 — 사용자 요청("3초 안에 말을 시작하면 듣기")을 그대로 구현."""
        return arrived - (n_samples / float(sample_rate))

    def _on_wake_utterance(self, pcm: np.ndarray) -> None:
        # WakeListener가 같은 루프에서 호출. self._task로 돌려 PTT 바지인이
        # 기존 경로 그대로 취소할 수 있게 한다.
        if not self._wake_gate():
            # 전달 시점에 전체 게이트(상태+에코 쿨다운)를 재판정한다 — 폴링 게이트만
            # 믿으면 게이트가 닫히기 직전 버퍼된 발화가 새어 들어온다.
            return
        if self._task is not None and not self._task.done():
            return
        arrived = asyncio.get_running_loop().time()
        self.state = State.TRANSCRIBING
        self._publish("thinking")  # 웨이크 변환 중에도 오브가 반응하도록
        self._task = asyncio.create_task(self._handle_wake(pcm, arrived))

    async def _handle_wake(self, pcm: np.ndarray, arrived: float | None = None) -> None:
        try:
            loop = asyncio.get_running_loop()
            t0 = loop.time()
            # follow-up 판정은 '말을 시작한' 시각 기준(도착 시각 − 캡처 길이) — 3초 창
            # 끝자락에서 시작해 길게 말한 명령이 '끝낸 시각'으로 잘려 버려지지 않게 한다.
            ref = self._speech_start(arrived, len(pcm)) if arrived is not None else loop.time()
            in_follow_up = ref < self._follow_up_until
            prefix_n = int(self._WAKE_PREFIX_S * 16000)
            gate_pcm = pcm if in_follow_up or len(pcm) <= prefix_n else pcm[:prefix_n]
            text = await asyncio.to_thread(
                self.stt.transcribe, gate_pcm, 16000, self.settings.language)
            matched, command = match_wake(text, self.settings.wake_words)
            if not matched and in_follow_up:
                command = text.strip()  # follow-up 창: 웨이크워드 생략 가능
                matched = bool(command)
            if not matched:
                self._to_idle()  # 우리 부른 게 아니다 — 즉시 폐기(로그 금지)
                return
            if len(gate_pcm) < len(pcm):
                full_text = await asyncio.to_thread(
                    self.stt.transcribe, pcm, 16000, self.settings.language)
                m2, c2 = match_wake(full_text, self.settings.wake_words)
                if m2:
                    command = c2  # 전문에서 명령을 다시 뽑는다(접두 변환은 잘려 있다)
            if not command:
                # "자비스"만 불렀다 — 바로 인사로 막지 말고 3초 듣는다(사용자 요청).
                self._listen_after_wake()
                return
            self._last_stt_s = loop.time() - t0
            await self._pipeline_text(command)
        except Exception as exc:  # noqa: BLE001 - 웨이크 경로는 스스로 회복해야 한다
            await self._announce_error(exc)

    async def _wake_greet(self) -> None:
        await self._play_phrase("Yes, sir?", "네, 주인님?")
        await self._finish_speaking("")
        self.state = State.IDLE
        self._enter_attentive()  # 웨이크 경로에서만 도달 — 리스너 존재가 보장된다

    def _listen_after_wake(self) -> None:
        """"자비스"만 불렀을 때: 바로 "네 주인님?"으로 마이크를 막지 않고, wake_grace_s초
        동안(웨이크워드 생략 가능) 듣는다. 그 안에 '말을 시작하면' 그 발화를 명령으로
        받는다(_handle_wake의 follow-up 경로). 정적이면 그제야 가볍게 인사한다. 우리가
        말하지 않으니 에코 쿨다운 0 — 사용자가 곧장 말해도 첫 음절이 잘리지 않는다."""
        self.state = State.IDLE
        self._enter_attentive(window=self.settings.wake_grace_s,
                              greet_if_idle=True, echo_cooldown=0.0)

    def _enter_attentive(self, *, window: float | None = None,
                         greet_if_idle: bool = False,
                         echo_cooldown: float | None = None) -> None:
        # follow-up 창을 열고 HUD에 '아직 듣는 중'을 은은하게 표시한다.
        loop = asyncio.get_running_loop()
        win = self.settings.follow_up_s if window is None else window
        cd = self.settings.wake_echo_cooldown_s if echo_cooldown is None else echo_cooldown
        self._follow_up_until = loop.time() + win
        self._wake_blocked_until = loop.time() + cd
        self._greet_if_idle = greet_if_idle
        self._publish("attentive")
        if self._attentive_timer is not None and not self._attentive_timer.done():
            self._attentive_timer.cancel()
        # 강한 참조는 이 속성이 보유한다(다음 창에서 교체) — _bg_tasks 중복 등재 불필요.
        self._attentive_timer = asyncio.create_task(self._attentive_expiry())

    async def _attentive_expiry(self) -> None:
        loop = asyncio.get_running_loop()
        await asyncio.sleep(max(0.0, self._follow_up_until - loop.time()))
        # 창이 연장(새 답변/명령)되지 않았고 여전히 한가할 때만 처리.
        if self.state == State.IDLE and loop.time() >= self._follow_up_until:
            if self._greet_if_idle:
                # 3초간 말이 없었다 — 그제야 "네 주인님?"으로 응답(이후 일반 follow-up 창).
                self._greet_if_idle = False
                self._attentive_timer = None  # 자기 자신 취소 회피(_wake_greet이 새 창을 연다)
                await self._wake_greet()
            else:
                self._publish("idle")

    # ----- 전권 위임 모드 -----
    def _trust_command(self, text: str) -> str | None:
        if "전권" not in text:
            return None
        if any(w in text for w in self._INTERP_OFF):
            return "off"
        if "켜져" in text or "켜졌" in text:
            return None
        if "켜" in text:
            return "on"
        return None

    async def _toggle_trust(self, cmd: str) -> None:
        if cmd == "on":
            TRUST_GATE.enable(self.settings.trust_mode_ttl_s)
            en, ko = ("Full authority granted, sir. I'll tidy up after myself shortly.",
                      "전권을 위임받았습니다, 주인님. 잠시 후 자동으로 닫습니다.")
        else:
            TRUST_GATE.disable()
            en, ko = ("Full authority revoked, sir.", "전권 모드를 껐습니다.")
        await self._play_phrase(en, ko)
        await self._finish_speaking("")
        self.state = State.IDLE
        if self.wake is not None:
            self._enter_attentive()
        else:
            self._publish("idle")

    # ----- 사용량 확인 -----
    def _usage_command(self, text: str) -> bool:
        t = text.replace(" ", "")
        return ("사용량" in t) or ("토큰" in t and ("얼마" in t or "확인" in t or "사용" in t))

    # ----- HUD A↔B(expand) 전환 -----
    def _expand_command(self, text: str):
        t = text.replace(" ", "")
        if any(w in t for w in ("크게띄워", "크게보여", "패널크게", "확대", "크게켜")):
            return True
        if any(w in t for w in ("작게", "축소", "줄여")) and "화면" not in t:
            return False
        return None

    # ----- 화면 상시 인지(감시 모드) -----
    def _watch_command(self, text: str) -> bool | None:
        t = text.replace(" ", "")
        off_words = ("화면그만", "화면감시꺼", "그만봐")
        on_words = ("화면봐줘", "화면봐", "화면지켜봐", "화면같이보자", "화면감시켜")
        if "화면" in t and any(w in t for w in off_words):
            return False
        if any(w in t for w in on_words):
            return True
        return None

    async def _toggle_watch(self, on: bool) -> None:
        if on and self._watch_task is None:
            self._watch_task = asyncio.get_running_loop().create_task(self._watch_loop())
            await self._play_phrase("Keeping an eye on your screen, sir.",
                                    "화면을 계속 보고 있겠습니다.")
        elif not on and self._watch_task is not None:
            self._watch_task.cancel()
            self._watch_task = None
            await self._play_phrase("Standing down the watch, sir.",
                                    "화면 감시를 껐습니다.")
        else:
            sub = "이미 보고 있습니다." if on else "지금은 화면을 보고 있지 않습니다."
            await self._play_phrase("Very well, sir.", sub)
        self._to_idle()

    async def _watch_loop(self) -> None:
        """5초마다 화면을 캡처해 두뇌가 항상 최신 화면을 Read할 수 있게 한다."""
        from ..tools.jarvis_mcp import capture_screen_action
        interval = float(getattr(self.settings, "watch_interval_s", 5.0))
        with contextlib.suppress(asyncio.CancelledError):
            while True:
                try:
                    await asyncio.to_thread(capture_screen_action)
                except Exception:  # noqa: BLE001 - 캡처 한 번 실패는 무시
                    pass
                await asyncio.sleep(interval)

    def _watch_context(self) -> str:
        """감시 모드 중이면 두뇌 입력 앞에 최신 화면 안내를 깔아준다."""
        if self._watch_task is None:
            return ""
        return ("[화면 감시 중 — 최신 화면이 ~/.jarvis/screenshots/shot.png 에 5초마다 "
                "갱신된다. '지금 화면/이거' 류 질문이면 Read로 보고 답하라]\n")

    # ----- 백그라운드 자율 작업 -----
    async def _run_bg_task(self, desc: str) -> str:
        """일회용 두뇌로 위임 작업을 끝까지 수행하고 한국어 결과를 돌려준다."""
        factory = getattr(self, "bg_brain_factory", None)
        if factory is None:
            raise RuntimeError("백그라운드 두뇌 팩토리가 없습니다")
        brain = factory()
        try:
            chunks: list[str] = []
            prompt = ("[백그라운드 작업 — 사용자가 자리 비움. 도구로 끝까지 수행하고 "
                      "마지막에 결과를 한국어로 정리하라. 확인 질문 금지]\n" + desc)
            async for piece in brain.respond(prompt):
                chunks.append(piece)
            result = getattr(brain, "last_subtitle", "") or " ".join(chunks)
            return result.strip()
        finally:
            close = getattr(brain, "close", None)
            if close is not None:
                with contextlib.suppress(Exception):
                    await close()

    async def _bg_task_done(self, task) -> None:
        """완료 보고: 결과 파일 저장 + 패널 + 능동 음성 보고."""
        try:  # 결과 영구 저장 (~/.jarvis/tasks/)
            from pathlib import Path
            d = Path.home() / ".jarvis" / "tasks"
            d.mkdir(parents=True, exist_ok=True)
            fname = d / f"task{task.id}-{task.started.replace(':', '')}.md"
            fname.write_text(f"# {task.desc}\n\n상태: {task.status}\n\n{task.result}\n",
                             encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        self._panel_sink(f"백그라운드 작업 #{task.id} {task.status}\n{task.desc}\n\n{task.result[:600]}")
        if self.proactive is not None:
            from time import monotonic
            from ..proactive.events import Announcement
            now = monotonic()
            word = "끝났다" if task.status == "done" else "실패했다"
            self.proactive.enqueue(Announcement(
                "bg_done",
                f"백그라운드 작업이 {word}: {task.desc[:60]} — 결과 요지를 한두 문장으로 "
                f"보고하라: {task.result[:300]}",
                2, now, now + 1800.0))

    # ----- 자가진단 -----
    def _selfcheck_command(self, text: str) -> bool:
        t = text.replace(" ", "")
        return ("자가진단" in t) or ("자가점검" in t) or ("상태점검" in t) or ("셀프체크" in t)

    async def _run_selfcheck(self) -> None:
        """시스템 자가진단 — 요점은 음성으로, 전체 보고서는 패널로."""
        from .selfcheck import format_report, run_checks, summary_line
        checks = await asyncio.to_thread(run_checks, self)
        summary = summary_line(checks)
        report = format_report(checks)
        print(f"[자가진단] {summary}")
        self._panel_sink(report)  # 명시 요청 — 패널 음소거 무시하고 표시
        await self._play_phrase("Self check complete, sir.", summary)
        await self._finish_speaking(summary)
        self.state = State.IDLE
        if self.wake is not None:
            self._enter_attentive()
        else:
            self._publish("idle")

    async def _report_usage(self) -> None:
        summary = self.usage.summary()
        print(f"[사용량] {summary}")
        await self._play_phrase("Here is your usage, sir.", summary)
        await self._finish_speaking(summary)  # 자막으로 사용량을 띄워 둔다
        self.state = State.IDLE
        if self.wake is not None:
            self._enter_attentive()
        else:
            self._publish("idle")

    async def _announce_limit(self) -> None:
        """LLM 한도/요금 초과 — 조용히 죽지 말고 화면에 '한도 초과' + 음성으로 알린다."""
        sub = "⚠ 한도 초과 — 잠시 후 다시 시도해 주세요."
        print("[한도] LLM 사용 한도/요금 초과로 응답하지 못했습니다.")
        self.state = State.SPEAKING
        self._publish("speaking", 0.4, sub)
        spoke = False
        if sys.platform == "darwin":  # macOS는 한국어로 직접 말한다
            try:
                await asyncio.to_thread(
                    interpret_speak_korean,
                    "사용 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.",
                    self.settings.interpret_ko_voice)
                spoke = True
            except Exception:  # noqa: BLE001
                spoke = False
        if not spoke:  # 그 외 플랫폼: 자비스 영어 음성으로 알린다
            await self._play_phrase(
                "I've reached my usage limit, sir. Please try again shortly.", sub)
        await self._finish_speaking(sub)
        self.state = State.IDLE
        if self.wake is not None:
            self._enter_attentive()
        else:
            self._publish("idle")

    async def _announce_error(self, exc: Exception) -> None:
        """버그/오류를 조용히 삼키지 말고 음성+우측 알림으로 알린다(수정 요청 가능하게)."""
        detail = (str(exc).strip() or exc.__class__.__name__)
        self.last_bug = detail
        short = detail if len(detail) <= 140 else detail[:137] + "…"
        print(f"[오류] {detail}")
        self._notify(f"⚠ 오류\n{short}")
        self.state = State.SPEAKING
        self._publish("speaking", 0.3, "⚠ 오류가 발생했어요.")
        spoke = False
        if sys.platform == "darwin":
            try:
                await asyncio.to_thread(
                    interpret_speak_korean,
                    "오류가 발생했습니다. 오른쪽 위를 확인해 주세요.",
                    self.settings.interpret_ko_voice)
                spoke = True
            except Exception:  # noqa: BLE001
                spoke = False
        if not spoke:
            await self._play_phrase(
                "Something went wrong, sir. Please check the top-right notice.",
                "⚠ 오류가 발생했어요.")
        await self._finish_speaking("")
        self._to_idle()

    # ----- 알림 패널 끄기/켜기 (순수 토글만 — 내용 요청은 두뇌의 show_panel로) -----
    def _panel_command(self, text: str) -> str | None:
        t = text.replace(" ", "")
        if ("패널" not in t) and ("알림" not in t):
            return None
        if any(w in t for w in ("꺼", "끄", "닫", "없애", "치워", "숨겨")):
            return "off"  # 끄기는 즉시·공격적으로(사용자 요구: 바로 끔)
        # 켜기는 "패널 켜줘"처럼 짧은 순수 토글일 때만 가로챈다. "패널에 일정 보여줘"
        # 같은 내용 요청을 여기서 삼키면 두뇌의 show_panel이 영영 못 뜬다(실제 버그).
        if "켜" in t and len(t) <= 10:
            return "on"
        return None

    async def _toggle_panel(self, cmd: str) -> None:
        self._panel_muted = (cmd == "off")
        if cmd == "off":
            if self.hud is not None:
                with contextlib.suppress(Exception):
                    self.hud.publish_notice("")  # 즉시 끈다
            en, ko = ("Notice panel off, sir.", "알림 패널을 껐습니다.")
        else:
            en, ko = ("Notice panel on, sir.", "알림 패널을 켰습니다.")
        await self._play_phrase(en, ko)
        await self._finish_speaking("")
        self.state = State.IDLE
        if self.wake is not None:
            self._enter_attentive()
        else:
            self._publish("idle")

    # ----- 통역 모드 -----
    _INTERP_ON = ("켜", "시작", "on")
    _INTERP_OFF = ("꺼", "끄", "종료", "off", "그만")

    def _interpret_command(self, text: str) -> str | None:
        if "통역" not in text:
            return None
        if any(w in text for w in self._INTERP_OFF):
            return "off"
        if any(w in text for w in self._INTERP_ON):
            return "on"
        return None

    async def _toggle_interpret(self, cmd: str) -> None:
        self.interpret_mode = (cmd == "on")
        if self.interpret_mode and hasattr(self.brain, "warm_interpret"):
            # 안내 발화가 나가는 동안 백그라운드 예열 — 첫 통역 턴 콜드스타트 제거.
            self._warm_task = asyncio.create_task(self._warm_interpret_safe())
        en, ko = (("Interpreter mode on, sir.", "통역 모드를 켰습니다.")
                  if self.interpret_mode
                  else ("Interpreter mode off, sir.", "통역 모드를 껐습니다."))
        await self._play_phrase(en, ko)
        await self._finish_speaking("")
        self.state = State.IDLE
        if self.wake is not None:
            self._enter_attentive()
        else:
            self._publish("idle")

    async def _warm_interpret_safe(self) -> None:
        try:
            await self.brain.warm_interpret()
        except Exception:  # noqa: BLE001 - 예열 실패는 무해
            pass

    async def _interpret_turn(self, text: str) -> None:
        try:
            src = detect_lang(text)
            if src == "ko":
                out = await self.brain.translate(text, "English")
                await self._speak(out)
                await self._finish_speaking("")
            else:
                out = await self.brain.translate(text, "Korean")
                self.state = State.SPEAKING
                self._publish("speaking", 0.4, out)  # 한국어 통역도 오브·자막 반응
                await asyncio.to_thread(
                    interpret_speak_korean, out, self.settings.interpret_ko_voice)
        except Exception as exc:  # noqa: BLE001 - 통역 한 줄 실패가 모드를 깨면 안 된다
            print(f"[통역] 오류: {exc}")
        self.state = State.IDLE
        if self.wake is not None:
            self._enter_attentive()
        else:
            self._publish("idle")

    # ----- 화면 제어 모드 (3c) -----
    def _control_command(self, text: str) -> str | None:
        # STT 띄어쓰기 변동("화면제어"/"화면 제어"/"제어 모드")에 강하게 — 공백 제거 비교.
        t = text.replace(" ", "")
        if "화면제어" not in t and "제어모드" not in t:
            return None
        if any(w in t for w in self._INTERP_OFF):
            return "off"
        if "켜져" in t or "켜졌" in t:
            return None  # 상태 질문("켜져 있어?") — 토글 아님, 두뇌로
        if "켜" in t:
            return "on"
        return None

    async def _toggle_control(self, cmd: str) -> None:
        # interpret과 달리 턴을 가로채는 모드가 아니다 — 게이트 플래그만 연다.
        # 두뇌는 평소 경로에서 capture_screen/screen_control을 쓴다.
        if cmd == "on":
            CONTROL_GATE.enable(self.settings.screen_control_ttl_s)
            en, ko = ("Screen control engaged, sir. It will switch itself off "
                      "in a few minutes.",
                      "화면 제어 모드를 켰습니다. 잠시 후 자동으로 꺼집니다.")
        else:
            CONTROL_GATE.disable()
            en, ko = ("Screen control disengaged, sir.", "화면 제어 모드를 껐습니다.")
        await self._play_phrase(en, ko)
        await self._finish_speaking("")
        self.state = State.IDLE
        if self.wake is not None:
            self._enter_attentive()
        else:
            self._publish("idle")

    # ----- 능동 알림 (ProactiveEngine이 호출) -----
    def _can_announce(self) -> bool:
        return (self.state == State.IDLE
                and not self._remote_busy
                and (self._task is None or self._task.done()))

    async def announce(self, prompt: str) -> None:
        # 같은 루프에서 불린다. self._task로 돌려 PTT/웨이크가 평소처럼 끼어들 수 있게.
        self._last_stt_s = None
        if not self._can_announce():
            return
        self.state = State.THINKING
        self._publish("thinking")  # 상태와 HUD는 한 쌍 — 게이트 선점과 동시에 표시
        self._task = asyncio.create_task(self._handle_announce(prompt))

    async def _handle_announce(self, prompt: str) -> None:
        try:
            await self._pipeline_text(f"[SYSTEM EVENT] {prompt}", ack=False)
        except Exception as exc:  # noqa: BLE001 - 알림 실패가 상태를 가두면 안 된다
            print(f"[능동] 처리 오류(IDLE 복귀): {exc}")
            self._to_idle()

    # ----- 아이폰 원격 명령 -----
    async def remote_turn(self, text: str) -> dict:
        """원격(HTTP) 텍스트 턴 — TTS 없이 텍스트로만 답한다(사용자 부재).
        THINKING 상태가 웨이크 게이트를 막고 _remote_busy가 PTT 경로를 막아
        두뇌 동시 사용(응답 훔치기 레이스)을 차단한다."""
        if not text.strip():
            return {"reply": "무엇을 도와드릴까요?"}
        if self._remote_busy or not self._can_announce():
            return {"reply": "지금 다른 일을 처리하고 있습니다. 잠시 후 다시 시도해 주세요."}
        self._remote_busy = True
        self.state = State.THINKING
        self._publish("thinking")
        if hasattr(self.brain, "remote_mode"):
            self.brain.remote_mode = True
        try:
            parts: list[str] = []
            # 원격 컨텍스트를 두뇌에 알린다 — 모르면 "보낼까요?" 같은 되묻기를 하는데,
            # 원격엔 음성 확인 채널이 없어 약속이 공중에 뜬다(라이브 검증에서 발견).
            remote_text = (
                "[원격 텍스트 메시지 — 사용자는 지금 컴퓨터 앞에 없다. 발송·앱 실행·"
                "화면 작업·패널 표시는 불가하니 약속하거나 되묻지 말고, 가능한 정보로 "
                f"바로 답하라]\n{text}")
            await self._await_warm()  # 첫 턴(원격)도 예열 대기 — warm/실쿼리 겹침 차단
            async for delta in self.brain.respond(remote_text):
                parts.append(delta)
            en = "".join(parts).strip()
            ko = (getattr(self.brain, "last_subtitle", "") or "").strip()
            return {"reply": ko or en or "답을 만들지 못했습니다.", "reply_en": en}
        except Exception as exc:  # noqa: BLE001 - 원격 한 턴 실패가 상태를 가두면 안 된다
            print(f"[원격] 처리 오류: {exc}")
            return {"reply": "처리 중 오류가 났습니다."}
        finally:
            if hasattr(self.brain, "remote_mode"):
                self.brain.remote_mode = False
            self._remote_busy = False
            self._to_idle()

    # Instant acknowledgements (English speech, Korean subtitle). Cached after first
    # synth so they play with zero delay — JARVIS answers the moment you stop talking.
    ACK_FILLERS = (
        ("One moment, sir.", "잠시만요."),
        ("Just a moment, sir.", "잠시만 기다려 주십시오."),
        ("Right away, sir.", "바로 처리하겠습니다."),
        ("Let me see, sir.", "확인해 보겠습니다."),
    )

    async def _play_ack(self) -> None:
        en, ko = self.ACK_FILLERS[self._ack_i % len(self.ACK_FILLERS)]
        self._ack_i += 1
        await self._play_phrase(en, ko)

    async def _synth_phrase(self, en: str) -> np.ndarray | None:
        out = self._ack_cache.get(en)
        if out is None:
            try:
                audio = await self.tts.synth(en)
                conv = await asyncio.to_thread(self.vc.convert, audio, self.tts.sample_rate)
                out = resample(np.asarray(conv, dtype=np.float32).reshape(-1),
                               self.vc.sample_rate, self.settings.playback_rate)
            except Exception:  # noqa: BLE001 - canned phrase is best-effort
                return None
            self._ack_cache[en] = out
        return out

    async def _play_phrase(self, en: str, ko: str) -> None:
        out = await self._synth_phrase(en)
        if out is None:
            return
        self._queue_audio(out, ko)

    async def warm_phrases(self) -> None:
        # 부팅 직후 호출 — 캔드 프레이즈를 미리 합성해 첫 ACK·인사도 0지연.
        for en, _ko in (*self.ACK_FILLERS, ("Yes, sir?", "네, 주인님?")):
            await self._synth_phrase(en)

    def _queue_audio(self, out: np.ndarray, subtitle: str | None = None) -> None:
        # 발화 송출의 단일 꼬리: 상태 전환 → HUD(자막 포함) → 레벨 펌프 → 재생.
        # 캔드 프레이즈(_play_phrase)와 문장(_speak)이 같은 경로를 타야 펌프/HUD
        # 수정이 한쪽만 적용되는 사고가 없다.
        self.state = State.SPEAKING
        self._publish("speaking", audio_level(out), subtitle)
        for lv in chunk_levels(out, self.settings.playback_rate, _HUD_HOP_S):
            self._spk_levels.put_nowait(lv)
        if self._spk_pump is None or self._spk_pump.done():
            self._spk_pump = asyncio.create_task(self._spk_pump_loop())
        self.playback.feed(out)

    async def _speak(self, sentence: str, subtitle: str | None = None) -> None:
        # Empty/whitespace chunks make MeloTTS emit empty audio, which crashes RVC
        # (zero-size reduction) and killed the whole turn with no sound — skip them.
        if not sentence.strip():
            return
        self.state = State.SPEAKING
        # 합성을 1회 재시도한다 — 일시적 TTS 오류로 문장을 통째로 잃으면(=말이 끊김)
        # 안 되므로. 두 번 다 실패할 때만 포기한다.
        audio = None
        for _attempt in range(2):
            try:
                audio = await self.tts.synth(sentence)            # at tts.sample_rate
                break
            except Exception:  # noqa: BLE001 - 마지막 시도까지 실패하면 그 문장만 건너뜀
                audio = None
        if audio is None:
            return
        arr = np.asarray(audio, dtype=np.float32).reshape(-1)
        if arr.size == 0 or float(np.max(np.abs(arr))) < 1e-4:  # empty/silent crashes RVC
            return
        audio = arr
        try:
            converted = await asyncio.to_thread(self.vc.convert, audio, self.tts.sample_rate)
            out = resample(converted, self.vc.sample_rate, self.settings.playback_rate)
        except Exception:  # noqa: BLE001 - RVC failed: speak base voice, never go silent
            out = resample(np.asarray(audio, dtype=np.float32).reshape(-1),
                           self.tts.sample_rate, self.settings.playback_rate)
        self._queue_audio(out, subtitle or None)

    async def _spk_pump_loop(self) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            while True:
                try:
                    lv = self._spk_levels.get_nowait()
                except asyncio.QueueEmpty:
                    break
                self._publish("speaking", lv)
                await asyncio.sleep(_HUD_HOP_S)

    def _drain_levels(self) -> None:
        while not self._spk_levels.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._spk_levels.get_nowait()

    # ----- run loop -----
    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.playback.start()
        if self.micstream is not None and self.wake is not None:
            # 웨이크 모드에서만 상시-온. PTT 전용이면 누를 때만 연다(프라이버시).
            # 열기 실패는 부팅을 막지 않는다 — _want_running이 켜진 채라 웨이크
            # 루프의 ensure_running()이 2초 간격으로 자가 복구를 시도한다.
            try:
                self.micstream.start()
            except Exception as exc:  # noqa: BLE001
                print(f"[마이크] 입력 스트림 시작 실패(자동 재시도): {exc}")
        if self.wake is not None:
            self.wake.start(self._on_wake_utterance, self._wake_gate)
        if self.proactive is not None:
            self.proactive.start()
        self.activator.start(self._press, self._release)
        await asyncio.Event().wait()  # run until process is killed
