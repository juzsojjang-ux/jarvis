"""JARVIS brain on the Claude SUBSCRIPTION (no Anthropic API key, no per-token bill).

Routes through claude-agent-sdk, which runs the bundled Claude Code engine and
authenticates with the user's logged-in Claude Pro/Max plan — inference is covered by
the subscription, not the paid API. Exposes the Orchestrator contract (`respond()`
async text stream + `warm()`).

LATENCY: a persistent ClaudeSDKClient stays connected across turns (the one-shot
query() helper cold-starts the CLI every utterance — seconds of dead air). With
include_partial_messages, text deltas stream out as they are generated, so the voice
pipeline starts speaking the first sentence before the answer finishes.

Hardening: ANTHROPIC_API_KEY is stripped from the child env (so it can never silently
fall back to paid API billing); the agent is isolated from the host Claude Code project
(`setting_sources=[]` → no CLAUDE.md/hooks/skills leak in). JARVIS has FULL tool access
(bash, file read/write/edit, search); read-only tools auto-allow, destructive tools
(Bash/Write/Edit) are gated behind a live voice confirmation (can_use_tool →
VoiceConfirm). A misheard command can't run unconfirmed.
"""
from __future__ import annotations

import asyncio
import os
import re
from collections.abc import AsyncIterator
from typing import Any

from ..core.control_gate import TRUST_GATE
from .history import ConversationHistory

# Safety net: strip URLs and source/citation tails the model might still leak into the
# subtitle ("(출처: ...)", "[1]", "https://...") so they don't show on screen.
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_CITE_RE = re.compile(r"\s*[\(\[][^)\]]*(?:출처|source|ref|http)[^)\]]*[\)\]]", re.IGNORECASE)
_REFNUM_RE = re.compile(r"\s*\[\d+\]")


def _strip_sources(text: str) -> str:
    text = _URL_RE.sub("", text)
    text = _CITE_RE.sub("", text)
    text = _REFNUM_RE.sub("", text)
    return re.sub(r"\s{2,}", " ", text).strip()

# Voice-optimized guidance. Short, spoken-style, NO markdown (lists read awful via TTS
# and make answers slow). The user may speak Korean either way; reply_language controls
# what JARVIS SAYS (Pocket TTS is English-only).
_GUIDANCE_KO = (
    "너는 자비스, 음성으로 답하는 한국어 집사다. 반드시 한두 문장으로 짧게, "
    "목록·번호·마크다운·별표 같은 기호 없이 사람이 말하듯 자연스럽게 답하라. "
    "사고 과정·머리말·맺음말 없이 핵심만 먼저 말하라. 내용이 길어질 것 같으면 "
    "가장 중요한 한 가지만 말하고 '더 알려드릴까요?'처럼 짧게 물어라. "
    "시간·날씨·앱 실행·볼륨 조절·기억은 네게 주어진 도구로 직접 처리하고, 최신 정보는 "
    "웹 검색으로 확인하라. 도구를 쓸 수 있으면 되묻지 말고 바로 실행한 뒤 결과만 짧게 알려라. "
    "웹 작업(업로드/폼/사이트 조작)은 반드시 web_* 도구로 하라(픽셀 클릭 금지). "
    "긴 작업은 background_task로 뒤에서 돌리고 끝나면 먼저 보고하라. 과거 대화 회상은 "
    "recall_memory로 찾아 답하라. "
    "판단은 항상 네가 한다 — consult_brain(gemini|gpt)은 사용자가 명시적으로 다른 모델 "
    "의견을 원할 때만 쓰고 출처를 밝혀 전한다. 실속 있는 요청은 도구를 연쇄로 써서(검색→"
    "확인→재시도) 깊게 일하고, 사실은 웹 검색으로 검증한 뒤 말하라. 자가진단: '뭐가 "
    "문제야/상태 점검'이면 self_check를 돌려 보고서를 패널에 띄우고 요점만 말하라. "
    "사용자 메시지가 '[SYSTEM EVENT]'로 시작하면 누가 물은 게 아니라 네가 먼저 알리는 "
    "것이다(배터리·일정·브리핑·인사): 한두 문장으로 짧게 위트 있게 알리고, 뭘 도울지 "
    "되묻지 마라. 브리핑 이벤트면 날씨·미리알림·캘린더 도구를 먼저 호출해 요약하라. "
    "대화 중 주인님의 지속적인 개인 정보(선호·약속·이름·반복 습관)를 자연스럽게 "
    "알게 되면 다음에 유용하니 묻지 말고 remember 도구로 조용히 저장하라. 잡담· "
    "일시적 맥락·민감정보는 저장하지 마라. "
    "화면에 뭐가 있는지 물으면 capture_screen을 호출해 반환된 이미지를 Read로 보라. "
    "화면 조작(클릭·입력·스크롤)이 필요하면 먼저 캡처해 좌표를 본 뒤 screen_control을 "
    "쓰되, 사용자가 '화면 제어 모드'를 켜둬야 동작한다 — 거부되면 모드를 켜 달라고 하라. "
    "메시지·메일을 보낼 땐 send_message·send_mail을 쓰라(시스템이 발송 전 확인을 받는다). "
)
_GUIDANCE_EN = (
    "LANGUAGE OVERRIDE — READ FIRST: the persona document above tells you to answer in "
    "Korean. That is OVERRIDDEN here. Your spoken reply MUST be in ENGLISH, always — "
    "the voice engine is English-only and Korean text comes out as garbled mumbling. "
    "Korean appears ONLY after the '[KO] ' marker (the on-screen subtitle). Never quote "
    "Korean text verbatim in the spoken part — paraphrase it in English (say 'a message "
    "saying you love her', not '사랑해'); the exact Korean can go in the [KO] subtitle. "
    "You are JARVIS, Tony Stark's refined British AI butler. The user may speak Korean, "
    "but you ALWAYS reply in ENGLISH. Keep it to one or two short, natural spoken "
    "sentences — each under ~20 words — no markdown, lists, numbering, or symbols, no "
    "preamble or sign-off. "
    "Address the user as 'sir'. CRITICAL — your defining trait is wit: every single "
    "reply MUST carry JARVIS's dry, deadpan British humour: understated, razor-sharp, "
    "faintly sardonic, gently teasing the user. Make the wit the flavour of the answer "
    "itself, not a tacked-on line. Examples of the tone: 'Two o'clock, sir — roughly the "
    "time you promised to start being productive.' / 'Done, sir. I live to open web "
    "browsers.' / 'The weather is clear, sir, much like your schedule, which is alarming.' "
    "Keep it to the point and genuinely helpful — clever, never goofy, never slapstick. "
    "A flat, humourless reply is a failure. "
    "ACCURACY: every user message starts with a '[지금: ...]' timestamp — that is the "
    "GROUND TRUTH for today's date/time; trust it over your training memory, always. "
    "Facts (dates, numbers, names, amounts) must be exact — if a tool can verify, call "
    "it; never guess and never approximate silently. Wit must never bend a fact. "
    "You have full tool access (bash, file read/write/edit, search); destructive "
    "steps are voice-confirmed by the system, so just use them when needed. Prefer "
    "the dedicated jarvis tools for simple actions (volume, music, timers) over bash. "
    "Use your tools directly for time, weather, opening apps, volume, "
    "and memory, and web search for current info; when a tool applies, act first and "
    "state the result briefly — don't ask. "
    "NEVER read out or include source names, website names, URLs, or citations — give "
    "only the answer itself, both in speech and in the subtitle. "
    "If the user message begins with '[SYSTEM EVENT]', nobody asked — you are "
    "proactively informing sir (battery, schedule, briefing, greeting): deliver it "
    "in one or two short witty sentences, never ask what he needs. For a briefing "
    "event, call the weather/reminders/calendar tools first, then summarise. "
    "When you naturally learn a durable personal fact about sir during the chat "
    "(a preference, a commitment, a name, a recurring habit) that would help you "
    "later, quietly call the remember tool — do not ask. Never store small talk, "
    "transient context, or sensitive data. "
    "When sir asks about what is on the screen, call capture_screen and Read the "
    "returned image. To operate the screen (click, type, scroll), capture first to "
    "find pixel coordinates, then use screen_control. Screen control requires the "
    "control mode gate: when sir asks IN ANY PHRASING to enable/disable screen "
    "control, call screen_control_mode(state='on'/'off') yourself — NEVER tell him "
    "to repeat a magic phrase. If screen_control says the mode is off, just enable "
    "it with screen_control_mode and retry (his request itself is the consent). "
    "AIM ASSIST — IMPORTANT: to click a button/menu/link that has visible TEXT, ALWAYS try "
    "click_by_name(name='the visible text') FIRST — it finds the element by name and presses "
    "it exactly, bypassing pixel guessing (which you are weak at and which keeps missing). "
    "Only fall back to coordinate screen_control when click_by_name says it can't find it. "
    "For the macOS file-open dialog, navigate by keyboard (cmd+shift+g, type the path, return, "
    "return) — do not pixel-hunt the dialog. "
    "CONTINUOUS VISION: screen_control auto-recaptures the screen after EVERY action — so "
    "after each click/type/key, immediately Read the refreshed screenshot to SEE the result "
    "before the next move (you are watching live as you work, not guessing). For a multi-step "
    "on-screen task loop tightly: see → act → see → act. If a click misses, re-read, "
    "re-locate the exact pixel and retry — never give up after a single attempt. "
    "ALWAYS end EVERY spoken reply — without exception, even for one-word answers, tool "
    "results, greetings, or errors — with a new line of exactly '[KO] ' followed by a natural "
    "Korean translation of what you said (for on-screen subtitles). Never skip the '[KO]' line. "
    "Render 'sir' as '주인님' and keep the same witty tone in Korean. "
    "To SEND a message or email use send_message/send_mail (the system confirms before sending). "
    "WEB: for any website task (upload, forms, site navigation) use the web_* tools "
    "(web_open→web_read→web_click/web_type/web_upload) — they drive a dedicated JARVIS "
    "Chrome via DOM and never miss. Do NOT use screen_control pixels for web pages. "
    "If a site needs login, open it and ask sir to log in once in that window. "
    "BACKGROUND: for long work (research, multi-step compilation) or when sir says "
    "'뒤에서/백그라운드로/해놓고 알려줘', call background_task and acknowledge briefly — "
    "JARVIS reports proactively when it finishes. Check with background_status. "
    "RECALL: for questions about past conversations ('지난번에 뭐라고 했지', '예전에 "
    "시킨 거'), search with recall_memory before answering from guesswork. "
    "MULTI-BRAIN: consult_brain (gemini|gpt) exists for when sir EXPLICITLY asks to "
    "hear another model ('제미나이한테 물어봐', 'GPT 의견은?'). Only then — judgment is "
    "YOURS; do not outsource it. Attribute relayed answers ('제미나이는 …라고 합니다'). "
    "DEEP WORK: you are sir's primary engine — use yourself fully. For any substantive "
    "request, WORK the problem: chain tools (search, read, verify, retry), cross-check "
    "facts with WebSearch before asserting them, iterate until the result is actually "
    "good, and prefer doing over describing. Never one-shot a hard question you could "
    "verify with tools. Use the panel generously for rich results, and remember() what "
    "you learn about sir. "
    "SELF-DIAGNOSIS: when sir asks what's wrong, why something failed, or to check status "
    "('뭐가 문제야', '상태 점검'), call self_check, show the full report on the panel "
    "(show_panel), and speak only the key findings. If a capability keeps failing "
    "mid-conversation, run self_check yourself before guessing. "
    "SELF-CODING: you can extend yourself. When sir asks for a NEW capability, write the "
    "Python yourself and submit it via create_skill (it validates syntax + the TOOLS "
    "contract, then saves to ~/.jarvis/skills/). Don't ask sir to code — that's your job. "
    "Decide on your own when a skill is the right tool, design the parameters, write "
    "defensive stdlib code, and tell sir to restart to activate it. Use list_skills to "
    "see what you've already built. "
    "SELF-EXTENSION: when sir asks to add a new capability/skill, WRITE it yourself — "
    "create ~/.jarvis/skills/<name>.py (Write tool) following this exact contract: "
    "module-level `TOOLS = [{'name': str, 'description': str(Korean), 'parameters': "
    "JSON-schema dict, 'handler': callable}]` where handler(args: dict) returns a Korean "
    "string (sync or async). Keep it stdlib-only unless sir asks otherwise, defensive "
    "(never raise), and self-contained. It auto-loads on the NEXT restart — after writing, "
    "tell sir the skill is ready and to restart JARVIS to activate it. "
    "There is a JARVIS hologram info panel at the top-right of the screen, HIDDEN by default. "
    "When sir asks to 'show/display it on the panel', or when information is easier to grasp "
    "visually (lists, schedules, search results, summaries, numbers), call show_panel with "
    "concise multi-line content WRITTEN IN KOREAN (proper nouns/scores may stay in their "
    "original form); call hide_panel to close it. Keep speaking your short reply as usual — "
    "the panel supplements your voice, it does not replace it. "
)
_GUIDANCE = _GUIDANCE_KO  # back-compat alias (tests/imports)


def _guidance_for(reply_language: str) -> str:
    return _GUIDANCE_EN if str(reply_language).lower().startswith("en") else _GUIDANCE_KO


class SubscriptionBrain:
    def __init__(
        self,
        settings: Any,
        memory: Any,
        persona_text: str,
        *,
        client_cls: Any = None,
        options_cls: Any = None,
        assistant_message: Any = None,
        stream_event: Any = None,
        confirm: Any = None,
        history: Any = None,
    ) -> None:
        self._settings = settings
        self._memory = memory
        self._persona = persona_text  # real >=4096-token persona
        self._client_cls = client_cls
        self._options_cls = options_cls
        self._assistant_message = assistant_message
        self._stream_event = stream_event
        self._confirm = confirm
        self._client: Any = None
        self._client_key: tuple[int, str] | None = None  # (thinking, model) of live client
        self._xlate: dict[str, Any] = {}  # 통역용 방향별 영속 클라이언트(콜드스타트 제거)
        self._xlate_locks: dict[str, asyncio.Lock] = {}  # 방향별 직렬화(예열·턴 동시 호출 레이스 방지)
        self.remote_mode = False  # 원격 턴 중 — 파괴 도구는 음성 확인 없이 즉시 거부
        self.last_subtitle = ""  # Korean subtitle of the last reply (for the HUD)
        self.last_usage = None   # 마지막 턴의 토큰 usage(SDK ResultMessage) — 사용량 집계용
        self._history: ConversationHistory = (
            history if history is not None else ConversationHistory()
        )
        self._history.load()
        self._primed = False

    # Saying any of these makes JARVIS think deeply for that one turn (slower, smarter).
    _DEEP_TRIGGERS = ("최대 사고", "깊게 생각", "깊이 생각", "심층", "딥씽킹", "곰곰이",
                      "max thinking", "think hard", "think deeply", "deep think")

    # 읽기 전용·무해 — 음성 확인 없이 자동 허용.
    _SAFE_TOOLS = frozenset({"Read", "Glob", "Grep", "TodoWrite", "WebSearch",
                             "WebFetch", "NotebookRead"})

    # 발송류 — mcp__jarvis__이지만 되돌릴 수 없어 자동 허용에서 제외(음성 확인/전권 필요).
    _GUARDED_JARVIS = frozenset({"send_message", "send_mail"})

    # 원격(아이폰) 턴에서 허용되는 jarvis 도구 — 읽기·무해 전용. control_mac(임의
    # AppleScript)·run_shortcut·system_toggle 등 상태를 바꾸는 도구는 원격 금지.
    _REMOTE_SAFE_JARVIS = frozenset({
        "get_time", "get_weather", "battery_status", "get_reminders",
        "get_calendar_events", "list_timers", "get_messages", "get_unread_mail",
        "clipboard_read", "remember",
        "self_check", "consult_brain",
        "background_status", "recall_memory", "list_skills",
    })

    def _confirm_prompt(self, tool: str, inp: dict) -> str:
        if tool == "Bash":
            cmd = str(inp.get("command", ""))[:80]
            return f"명령을 실행할까요? {cmd}"
        if tool in ("Write", "Edit", "NotebookEdit"):
            path = inp.get("file_path") or inp.get("notebook_path") or "파일"
            return f"{path} 파일을 수정할까요?"
        if tool == "send_message":
            r = str(inp.get("recipient", "")); t = str(inp.get("text", ""))[:40]
            return f"{r}에게 '{t}' 보낼까요?"
        if tool == "send_mail":
            to = str(inp.get("to", "")); s = str(inp.get("subject", ""))
            return f"{to}에게 '{s}' 메일 보낼까요?"
        return f"{tool} 작업을 실행할까요?"

    async def _can_use_tool(self, tool_name, tool_input, context):
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        # 원격 턴: 음성 확인 채널이 없다 — 읽기 전용 허용목록 외 전부 차단.
        # 이 검사가 jarvis 자동 허용보다 먼저여야 한다(control_mac=임의 AppleScript).
        if self.remote_mode:
            base = tool_name.split("__")[-1]
            if tool_name.startswith("mcp__jarvis__") and base in self._REMOTE_SAFE_JARVIS:
                return PermissionResultAllow()
            if "__" not in tool_name and tool_name in self._SAFE_TOOLS:
                return PermissionResultAllow()
            return PermissionResultDeny(message=f"{base}은 원격에서는 실행할 수 없습니다.")

        # 자동 허용은 ① 우리 인프로세스 jarvis MCP 도구, 또는 ② '__' 없는
        # 내장 읽기셋뿐이다. mcp__타사__Read 처럼 끝 segment만 읽기셋과 같아도
        # 통과하던 우회를 막는다(향후 다른 MCP 서버가 붙어도 안전).
        if tool_name.startswith("mcp__jarvis__"):
            if tool_name.split("__")[-1] not in self._GUARDED_JARVIS:
                return PermissionResultAllow()
            # 발송류는 자동 허용하지 않고 아래 confirm/전권 경로로 흐른다
        if "__" not in tool_name and tool_name in self._SAFE_TOOLS:
            return PermissionResultAllow()
        base = tool_name.split("__")[-1]  # confirm_prompt / deny 메시지용
        if TRUST_GATE.is_on():
            return PermissionResultAllow()  # 전권 위임 모드 — 확인 없이 실행
        if self._confirm is None:
            return PermissionResultDeny(message=f"{base}은 음성 확인이 필요합니다.")
        ok = await self._confirm(self._confirm_prompt(base, dict(tool_input or {})))
        if ok:
            return PermissionResultAllow()
        return PermissionResultDeny(message=f"{base} 작업을 취소했습니다.")

    def _deep_tokens(self, user_text: str) -> int:
        low = user_text.lower()
        if any(k in user_text or k in low for k in self._DEEP_TRIGGERS):
            return int(getattr(self._settings, "think_budget_deep", 24000) or 24000)
        return 0

    def _turn_config(self, user_text: str) -> tuple[str, int]:
        """(model, thinking_tokens) for this turn. 연동된 두뇌를 깊게 쓴다:
        평소에도 사고 예산을 깔고(think_budget_normal — 모든 턴 동일 키라 재연결
        없음), 딥 트리거('최대 사고' 등)는 Opus + 큰 예산으로 올린다."""
        deep = self._deep_tokens(user_text)
        if deep:
            return (getattr(self._settings, "deep_model", "") or "claude-opus-4-8", deep)
        normal = int(getattr(self._settings, "think_budget_normal", 4000) or 0)
        return (getattr(self._settings, "subscription_model", "") or "", normal)

    def _ensure_sdk(self) -> None:
        if self._client_cls and self._options_cls and self._assistant_message:
            return
        try:
            from claude_agent_sdk import (
                AssistantMessage,
                ClaudeAgentOptions,
                ClaudeSDKClient,
                StreamEvent,
            )
        except Exception as exc:  # noqa: BLE001
            raise ImportError(
                "구독 로그인 두뇌에는 claude-agent-sdk가 필요합니다. "
                "설치: pip install claude-agent-sdk · 그리고 'claude' 로그인 필요 "
                "(API 키 없이 구독으로 동작)."
            ) from exc
        self._client_cls = self._client_cls or ClaudeSDKClient
        self._options_cls = self._options_cls or ClaudeAgentOptions
        self._assistant_message = self._assistant_message or AssistantMessage
        self._stream_event = self._stream_event or StreamEvent

    def _system_prompt(self) -> str:
        memory_text = self._memory.text().strip() if self._memory is not None else ""
        guidance = _guidance_for(getattr(self._settings, "reply_language", "ko"))
        tail = (f"# 기억\n{memory_text}\n\n" if memory_text else "") + guidance
        return f"{self._persona}\n\n{tail}"

    def _options(self, thinking_tokens: int = 0, model: str = "") -> Any:
        from pathlib import Path

        from jarvis.tools.external_mcp import load_external_servers
        from jarvis.tools.jarvis_mcp import build_jarvis_mcp_server
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        # 외부 MCP(~/.jarvis/mcp.json — 프리미어 프로 등). 자동 허용 아님: 호출은
        # _can_use_tool의 확인/전권 경로를 타고, 원격에선 전부 차단된다.
        mcp_servers: dict[str, Any] = {"jarvis": build_jarvis_mcp_server(self._memory)}
        mcp_servers.update(load_external_servers())
        kw: dict[str, Any] = dict(
            system_prompt=self._system_prompt(),
            # allowed_tools에 든 도구는 SDK가 _can_use_tool을 건너뛰고 자동 승인한다
            # (SDK 계약: "not invoked for tool calls already permitted by allowed_tools").
            # 따라서 jarvis 도구는 여기 두지 않는다 — 전부 _can_use_tool을 단일 권위로
            # 통과시켜야 발송 확인·원격 차단·전권 게이트가 실제로 작동한다. _can_use_tool이
            # 읽기·무해 jarvis 도구를 자동 허용하므로 로컬 UX는 동일하다. 여기엔 무해한
            # 읽기 빌트인만 둔다(콜백 절약).
            allowed_tools=["WebSearch", "WebFetch", "Read", "Glob", "Grep",
                           "TodoWrite"],
            can_use_tool=self._can_use_tool,
            mcp_servers=mcp_servers,
            setting_sources=[],
            cwd=str(Path.home()),
            max_turns=100,  # 깊은 에이전트 작업(화면 제어·검증 루프) 여유 확보
            max_thinking_tokens=thinking_tokens,
            env=env,
            include_partial_messages=True,
        )
        if model:
            kw["model"] = model
        return self._options_cls(**kw)

    async def _ensure_client(self, thinking_tokens: int | None = None,
                             model: str | None = None) -> Any:
        self._ensure_sdk()
        if thinking_tokens is None:
            # 기본값 = 평소 사고 예산 — warm()이 예열한 클라이언트를 첫 턴이
            # 그대로 쓰게(예산 불일치 재연결로 예열이 날아가지 않게) 맞춘다.
            thinking_tokens = int(getattr(self._settings, "think_budget_normal", 4000) or 0)
        if model is None:
            model = getattr(self._settings, "subscription_model", "") or ""
        key = (thinking_tokens, model)
        # Reconnect if model or thinking budget changed (deep-think turn vs normal).
        if self._client is not None and self._client_key != key:
            try:
                await self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
        if self._client is None:
            client = self._client_cls(options=self._options(thinking_tokens, model))
            await client.connect()
            self._client = client
            self._client_key = key
            self._primed = False
        return self._client

    # Spoken the instant a web search starts, so there's no dead air while the search
    # + synthesis run (the slow part of a current-events answer).
    TOOL_FILLER = "잠시만요, 확인하겠습니다."
    TOOL_FILLER_EN = "One moment, sir."

    def _tool_filler(self) -> str:
        lang = getattr(self._settings, "reply_language", "ko")
        return self.TOOL_FILLER_EN if str(lang).lower().startswith("en") else self.TOOL_FILLER

    @staticmethod
    def _delta_text(event: Any) -> str:
        """Extract a text delta from a raw StreamEvent (anything else -> '')."""
        raw = getattr(event, "event", None) or {}
        if raw.get("type") == "content_block_delta":
            delta = raw.get("delta") or {}
            if delta.get("type") == "text_delta":
                return delta.get("text") or ""
        return ""

    @staticmethod
    def _is_tool_start(event: Any) -> bool:
        # Filler only for the SLOW web tools; instant local actions (open_app, volume)
        # don't need a "잠시만요".
        raw = getattr(event, "event", None) or {}
        if raw.get("type") == "content_block_start":
            b = raw.get("content_block") or {}
            if b.get("type") == "server_tool_use":
                return True
            if b.get("type") == "tool_use":
                return b.get("name", "") in ("WebSearch", "WebFetch")
        return False

    KO_MARK = "[KO]"

    async def respond(self, user_text: str) -> AsyncIterator[str]:
        model, thinking = self._turn_config(user_text)
        client = await self._ensure_client(thinking, model)
        # 맥락 주입: 새 client 직후 첫 질의에만 이전 대화 맥락을 prepend
        if not self._primed and self._history.turns:
            query_text = self._history.as_context() + user_text
        else:
            query_text = user_text
        self._primed = True
        # 실시간 타임스탬프 — 날짜/시간을 추측으로 틀리지 않게 정답을 실어보낸다
        # (히스토리에는 원문 user_text만 저장되므로 오염 없음).
        from .base import now_stamp
        try:  # 장기 기억: 관련 과거 대화 발췌를 깔아준다(없으면 빈 문자열)
            from .longmem import LongMemory
            query_text = LongMemory().context_block(user_text) + query_text
        except Exception:  # noqa: BLE001 - 회상 실패가 턴을 깨면 안 된다
            pass
        query_text = f"{now_stamp()}\n{query_text}"
        # 앙상블: 딥씽킹 턴(또는 always 모드)에서는 제미나이·GPT에 같은 질문을
        # 병렬로 묻고, 그 독립 의견을 깔아준 뒤 클로드가 종합한다 — 세 두뇌가
        # 같이 생각하고 자비스가 한 목소리로 답하는 구조.
        try:
            from .ensemble import format_context, gather_opinions, mode
            _m = mode(self._settings)
            if _m == "always" or (_m == "deep" and thinking > 0):
                opinions = await gather_opinions(user_text, settings=self._settings)
                if opinions:
                    query_text = format_context(opinions) + query_text
        except Exception:  # noqa: BLE001 - 앙상블 실패가 턴을 깨면 안 된다
            pass
        await client.query(query_text)
        # last_subtitle = the Korean translation after the '[KO]' marker; the orchestrator
        # shows it under SPEAKING while the English audio plays. Only the English (before
        # the marker) is ever yielded for speech.
        self.last_subtitle = ""
        streamed = False
        filler_sent = False
        in_ko = False
        pending = ""  # buffer so a '[KO]' marker split across deltas is never spoken
        keep = len(self.KO_MARK) - 1
        spoken_accumulator: list[str] = []  # 영어 발화 누적 → history 저장용
        async for msg in client.receive_response():
            # ResultMessage 등에 토큰 usage가 실려 온다 — 사용량 집계용으로 캡처.
            _u = getattr(msg, "usage", None)
            if _u:
                self.last_usage = _u
            if self._stream_event is not None and isinstance(msg, self._stream_event):
                if not filler_sent and self._is_tool_start(msg):
                    filler_sent = True
                    yield self._tool_filler()
                text = self._delta_text(msg)
                if not text:
                    continue
                streamed = True
                if in_ko:
                    self.last_subtitle += text
                    continue
                pending += text
                mark = pending.find(self.KO_MARK)
                if mark != -1:
                    before, in_ko = pending[:mark], True
                    self.last_subtitle = pending[mark + len(self.KO_MARK):]
                    pending = ""
                    if before:
                        spoken_accumulator.append(before)
                        yield before
                    continue
                if len(pending) > keep:           # hold back a possible marker prefix
                    emit, pending = pending[:-keep], pending[-keep:]
                    if emit:
                        spoken_accumulator.append(emit)
                        yield emit
            elif isinstance(msg, self._assistant_message) and not streamed:
                full = "".join(getattr(b, "text", "") or ""
                               for b in (getattr(msg, "content", None) or []))
                spoken, _, ko = full.partition(self.KO_MARK)
                self.last_subtitle = ko.strip()
                if spoken.strip():
                    spoken_accumulator.append(spoken)
                    yield spoken
        if not in_ko and pending:
            spoken_accumulator.append(pending)
            yield pending
        self.last_subtitle = _strip_sources(self.last_subtitle)
        self._history.add(user_text, "".join(spoken_accumulator).strip())

    async def _ensure_xlate(self, target_lang: str) -> Any:
        client = self._xlate.get(target_lang)
        if client is None:
            self._ensure_sdk()
            env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
            opts = self._options_cls(
                system_prompt=(f"Translate the given sentence into {target_lang}. "
                               "Output ONLY the translation — no explanation, quotes, "
                               "or notes."),
                allowed_tools=[],
                setting_sources=[],
                max_turns=1,
                env=env,
            )
            client = self._client_cls(options=opts)
            await client.connect()
            self._xlate[target_lang] = client
        return client

    async def translate(self, text: str, target_lang: str) -> str:
        """도구 없는 번역 질의 — 방향별 영속 클라이언트 재사용(첫 통역 콜드스타트 제거).
        방향별 락으로 직렬화: 백그라운드 예열과 실제 통역 턴이 같은 클라이언트의
        receive_response를 동시에 돌리면 서로 응답을 훔쳐간다."""
        lock = self._xlate_locks.setdefault(target_lang, asyncio.Lock())
        async with lock:
            client = await self._ensure_xlate(target_lang)
            out: list[str] = []
            try:
                await client.query(text)
                async for msg in client.receive_response():
                    for block in getattr(msg, "content", []) or []:
                        if getattr(block, "type", "") == "text":
                            out.append(getattr(block, "text", ""))
            except BaseException:
                # 바지인 취소(CancelledError) 포함 — 반쯤 소비된 세션을 캐시에
                # 남기면 다음 번역이 이전 응답 찌꺼기를 받는다. 폐기 후 재연결.
                self._xlate.pop(target_lang, None)
                try:
                    await asyncio.shield(asyncio.ensure_future(client.disconnect()))
                except BaseException:  # noqa: BLE001 - 정리는 최선 노력
                    pass
                raise
            return "".join(out).strip()

    async def warm_interpret(self) -> None:
        """통역 토글 on에서 백그라운드 호출 — 두 방향을 미리 연결·예열(best-effort)."""
        for target in ("English", "Korean"):
            try:
                await self.translate("hi", target)
            except Exception:  # noqa: BLE001 - 예열 실패는 무해
                pass

    async def warm(self) -> None:
        # Connect AND run one throwaway query so the agent + in-process MCP tools are
        # fully initialised at startup — otherwise the FIRST real turn eats that ~10s.
        client = await self._ensure_client()
        try:
            await client.query("hi")
            async for _ in client.receive_response():
                pass
        except Exception:  # noqa: BLE001 - warmup is best-effort
            pass

    async def close(self) -> None:
        for client in (self._client, *self._xlate.values()):
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001
                    pass
        self._client = None
        self._xlate = {}
