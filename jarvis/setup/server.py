"""첫 실행 설정 서버 — stdlib ThreadingHTTPServer(orb_server 패턴 재사용).

GET /  → 설정 HTML 페이지(SETUP_HTML 인라인 상수).
POST /setup JSON {provider, key?} → 검증 후 저장, 완료 이벤트 set.

validator(provider, key) → (ok, msg) 비동기: 테스트에서 주입 가능.
store_save(provider, key) → None: 테스트에서 주입 가능.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .shortcut import create_desktop_shortcut as _default_shortcut
from .store import save_key, save_setup
from .validate import validate as _default_validate

# ---------------------------------------------------------------------------
# 설정 HTML — 영화풍 다크 테마, 세 카드, 한국어 레이블
# ---------------------------------------------------------------------------

SETUP_HTML = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>자비스 — 첫 실행 설정</title>
<style>
  :root {
    --bg: #0a0c10;
    --surface: #111520;
    --border: #1e2a3a;
    --accent: #00d4ff;
    --accent2: #0090cc;
    --text: #c8d8e8;
    --dim: #5a7080;
    --ok: #00e08a;
    --fail: #ff4455;
    --card-selected: #0d2035;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, "SF Pro Display", "Segoe UI", sans-serif;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 2rem 1rem;
  }
  .header {
    text-align: center;
    margin-bottom: 2.5rem;
  }
  .header h1 {
    font-size: 2rem;
    font-weight: 300;
    letter-spacing: 0.25em;
    color: var(--accent);
    text-transform: uppercase;
  }
  .header p {
    margin-top: 0.5rem;
    color: var(--dim);
    font-size: 0.9rem;
    letter-spacing: 0.05em;
  }
  .cards {
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
    justify-content: center;
    margin-bottom: 2rem;
  }
  .card {
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--surface);
    padding: 1.5rem 1.8rem;
    width: 200px;
    cursor: pointer;
    transition: border-color 0.2s, background 0.2s;
    user-select: none;
    position: relative;
  }
  .card:hover { border-color: var(--accent2); }
  .card.selected {
    border-color: var(--accent);
    background: var(--card-selected);
    box-shadow: 0 0 12px rgba(0,212,255,0.15);
  }
  .card .provider-name {
    font-size: 1.1rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    color: var(--accent);
    margin-bottom: 0.4rem;
  }
  .card .provider-note {
    font-size: 0.78rem;
    color: var(--dim);
    line-height: 1.4;
  }
  .badge {
    font-size: 0.6rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    padding: 0.1rem 0.4rem;
    border-radius: 0.6rem;
    vertical-align: middle;
  }
  .badge.free { background: #0d3a2a; color: #4ade80; }
  .badge.paid { background: #3a2a0d; color: #fbbf24; }
  .badge.sub { background:#1e2a3a; color:#7dd3fc; }
  .card input[type="radio"] { display: none; }
  .key-section {
    width: 100%;
    max-width: 440px;
    margin-bottom: 1.5rem;
    display: none;
  }
  .key-section.visible { display: block; }
  .key-section label {
    display: block;
    font-size: 0.82rem;
    color: var(--dim);
    margin-bottom: 0.5rem;
    letter-spacing: 0.04em;
  }
  .key-section input[type="text"] {
    width: 100%;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text);
    padding: 0.7rem 1rem;
    font-size: 0.95rem;
    outline: none;
    transition: border-color 0.2s;
    font-family: "SF Mono", "Menlo", monospace;
  }
  .key-section input[type="text"]:focus { border-color: var(--accent); }
  .btn-start {
    background: linear-gradient(135deg, var(--accent2), var(--accent));
    color: #000;
    font-weight: 700;
    font-size: 1rem;
    letter-spacing: 0.08em;
    border: none;
    border-radius: 8px;
    padding: 0.75rem 3rem;
    cursor: pointer;
    text-transform: uppercase;
    transition: opacity 0.2s;
  }
  .btn-start:hover { opacity: 0.85; }
  .btn-start:disabled { opacity: 0.4; cursor: default; }
  #msg {
    margin-top: 1.2rem;
    min-height: 1.4em;
    font-size: 0.9rem;
    text-align: center;
    transition: color 0.2s;
  }
  #msg.ok { color: var(--ok); }
  #msg.fail { color: var(--fail); }
  .done-box {
    display: none;
    flex-direction: column;
    align-items: center;
    gap: 0.6rem;
    margin-top: 1.5rem;
  }
  .done-box.visible { display: flex; }
  .done-box .checkmark { font-size: 2.5rem; }
  .done-box p { color: var(--ok); font-size: 1rem; letter-spacing: 0.04em; }
  .done-box small { color: var(--dim); font-size: 0.8rem; }
  .voice-panel {
    width: 100%; max-width: 480px; margin-top: 2.2rem;
    border-top: 1px solid var(--border); padding-top: 1.4rem;
  }
  .voice-panel h2 {
    font-size: 0.95rem; font-weight: 600; letter-spacing: 0.12em;
    color: var(--accent); text-transform: uppercase; margin-bottom: 0.5rem;
  }
  .voice-panel .vp-note {
    font-size: 0.8rem; color: var(--dim); line-height: 1.5; margin-bottom: 0.9rem;
  }
  .vp-modes { display: flex; flex-direction: column; gap: 0.4rem; margin-bottom: 0.9rem; }
  .vp-modes label { font-size: 0.82rem; color: var(--text); cursor: pointer; }
  .vp-modes input { margin-right: 0.5rem; accent-color: var(--accent); }
  .btn-upgrade {
    background: transparent; color: var(--accent); border: 1px solid var(--accent2);
    border-radius: 8px; padding: 0.6rem 1.6rem; font-size: 0.88rem; cursor: pointer;
    letter-spacing: 0.04em; transition: background 0.2s, opacity 0.2s;
  }
  .btn-upgrade:hover { background: var(--card-selected); }
  .btn-upgrade:disabled { opacity: 0.45; cursor: default; }
  .vp-log {
    display: none; margin-top: 1rem; max-height: 220px; overflow-y: auto;
    background: #06080c; border: 1px solid var(--border); border-radius: 6px;
    padding: 0.7rem 0.9rem; font-family: "SF Mono", "Menlo", monospace;
    font-size: 0.72rem; color: var(--dim); white-space: pre-wrap; line-height: 1.45;
  }
  .vp-log.visible { display: block; }
  .opt-row {
    display: flex; align-items: center; gap: 0.5rem; cursor: pointer;
    margin-bottom: 1.2rem; font-size: 0.85rem; color: var(--text); user-select: none;
  }
  .opt-row input { accent-color: var(--accent); width: 1rem; height: 1rem; }
  .voice-pick {
    width: 100%; max-width: 460px; margin-bottom: 1.3rem; text-align: left;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 1rem 1.2rem;
  }
  .voice-pick h3 {
    font-size: 0.85rem; color: var(--accent); letter-spacing: 0.1em;
    text-transform: uppercase; font-weight: 600; margin-bottom: 0.7rem;
  }
  .vp-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0.45rem 1rem; }
  .vp-grid label { font-size: 0.82rem; color: var(--text); cursor: pointer; }
  .vp-grid input { accent-color: var(--accent); margin-right: 0.4rem; }
  .name-row { margin-top: 0.9rem; }
  .name-row label { display: block; font-size: 0.8rem; color: var(--dim); margin-bottom: 0.35rem; }
  .name-row input {
    width: 100%; background: var(--bg); border: 1px solid var(--border);
    border-radius: 6px; color: var(--text); padding: 0.55rem 0.8rem; font-size: 0.95rem;
  }
  .name-row input:focus { border-color: var(--accent); outline: none; }
  .name-row small { display: block; margin-top: 0.35rem; color: var(--dim); font-size: 0.72rem; }
  .manual {
    margin-top: 1.2rem; max-width: 460px; text-align: left;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 1.1rem 1.3rem;
  }
  .manual h3 {
    font-size: 0.9rem; color: var(--accent); letter-spacing: 0.08em;
    margin-bottom: 0.7rem; text-transform: uppercase; font-weight: 600;
  }
  .manual ul { list-style: none; display: flex; flex-direction: column; gap: 0.55rem; }
  .manual li { font-size: 0.82rem; color: var(--text); line-height: 1.5; }
  .manual b { color: var(--accent); font-weight: 600; }
  .manual small { display: block; margin-top: 0.9rem; color: var(--dim); font-size: 0.75rem; }
</style>
</head>
<body>

<div class="header">
  <h1>J.A.R.V.I.S</h1>
  <p>두뇌를 선택하여 초기 설정을 완료하세요</p>
</div>

<div class="cards" id="cards">

  <label class="card selected" data-provider="claude">
    <input type="radio" name="provider" value="claude" checked>
    <div class="provider-name">Claude <span class="badge free">무료 · 추천</span></div>
    <div class="provider-note">구독 로그인 (키 불필요)<br>가장 강력 — Bash·파일·웹검색·화면비전</div>
  </label>

  <label class="card" data-provider="gemini">
    <input type="radio" name="provider" value="gemini">
    <div class="provider-name">Gemini <span class="badge free">무료</span></div>
    <div class="provider-note">Google AI Studio 무료 키<br>개인용 과금 없음 (도구·통역·기억 지원)</div>
  </label>

  <label class="card" data-provider="gpt">
    <input type="radio" name="provider" value="gpt">
    <div class="provider-name">GPT <span class="badge sub">구독</span></div>
    <div class="provider-note">ChatGPT 구독 로그인<br>버튼 한 번으로 로그인</div>
  </label>

</div>

<div class="key-section" id="keySection">
  <label id="keyLabel">API 키</label>
  <input type="text" id="keyInput" placeholder="키를 여기에 붙여넣으세요" autocomplete="off" spellcheck="false">
</div>

<div id="loginSection" style="display:none; width:100%; max-width:440px; margin-bottom:1.5rem; text-align:center;">
  <button id="btnLogin" type="button" style="padding:0.7rem 1.4rem; font-size:0.95rem; border-radius:10px; border:1px solid #38bdf8; background:#0b3a52; color:#e0f2fe; cursor:pointer;">로그인</button>
  <div id="loginStatus" style="margin-top:0.7rem; font-size:0.9rem; color:#7dd3fc;">로그인 상태를 확인하는 중…</div>
</div>

<div class="voice-pick" id="voicePick">
  <h3>목소리</h3>
  <div class="vp-grid">
    <label><input type="radio" name="vchoice" value="jarvis" checked> 자비스(영화 클론) · 영어</label>
    <label><input type="radio" name="vchoice" value="jarvis_ko"> 자비스(영화 클론) · 한국어</label>
    <label><input type="radio" name="vchoice" value="butler_en"> 영국 집사 · 영어</label>
    <label><input type="radio" name="vchoice" value="male_us"> 남성 · 영어(미국)</label>
    <label><input type="radio" name="vchoice" value="female_us"> 여성 · 영어(미국)</label>
    <label><input type="radio" name="vchoice" value="male_ko"> 남성 · 한국어</label>
    <label><input type="radio" name="vchoice" value="female_ko"> 여성 · 한국어</label>
  </div>
  <div class="name-row">
    <label for="aiName">어시스턴트 이름</label>
    <input type="text" id="aiName" value="자비스" maxlength="12" spellcheck="false">
    <small>부르는 말(웨이크워드)과 화면 표시가 이 이름으로 바뀝니다</small>
  </div>
  <div class="name-row">
    <label for="pttKey">말하기 키 (누르고 말하기)</label>
    <select id="pttKey" style="padding:.5rem .7rem;border-radius:8px;background:#0b1a26;color:#e0f2fe;border:1px solid rgba(94,224,255,.4);font-size:.95rem;">
      <option value="alt_r" selected>오른쪽 Alt (기본)</option>
      <option value="alt_l">왼쪽 Alt</option>
      <option value="ctrl_r">오른쪽 Ctrl</option>
      <option value="ctrl_l">왼쪽 Ctrl</option>
      <option value="shift_r">오른쪽 Shift</option>
      <option value="cmd_r">오른쪽 Cmd (맥)</option>
      <option value="space">스페이스바</option>
    </select>
    <small>이 키를 누른 채 말하면 자비스가 듣습니다 ("자비스" 음성 호출과 별개)</small>
  </div>
</div>

<label class="opt-row" id="shortcutRow">
  <input type="checkbox" id="deskShortcut" checked>
  <span>바탕화면에 자비스 아이콘(바로가기) 만들기</span>
</label>

<button class="btn-start" id="btnStart">시작</button>

<div id="msg"></div>

<div class="done-box" id="doneBox">
  <div class="checkmark">✓</div>
  <p>설정 완료 — 자비스를 시작합니다</p>
  <div class="manual">
    <h3>자비스 사용법</h3>
    <ul>
      <li><b>부르기</b> — "자비스"라고 부르거나, 오른쪽 <b>Option</b> 키를 누른 채 말하세요.</li>
      <li><b>대화</b> — 그냥 말하면 됩니다. 답이 끝나면 잠깐은 부르지 않아도 이어 말할 수 있어요.</li>
      <li><b>통역 모드</b> — "통역 켜" / "통역 꺼" (한↔영 통역).</li>
      <li><b>전권 위임</b> — "전권 켜" (확인 없이 작업 수행, 일정 시간 후 자동 해제).</li>
      <li><b>화면 제어</b> — "화면 제어 켜" (화면을 보고 클릭·입력).</li>
      <li><b>사용량 확인</b> — "사용량"이라고 하면 토큰 사용량을 알려줍니다.</li>
      <li><b>풀음성 업그레이드</b> — 위 <b>음성</b> 칸에서 개인용과 동일한 음색을 설치할 수 있어요.</li>
      <li><b>실행 표시</b> — 메뉴 막대(맥)/트레이(윈도우)의 자비스 아이콘으로 실행 중을 확인하고, 거기서 종료할 수 있습니다.</li>
    </ul>
    <small>이 창은 닫으셔도 됩니다.</small>
  </div>
</div>

<div class="voice-panel" id="voicePanel">
  <h2>음성</h2>
  <p class="vp-note">
    기본은 가볍고 안 멈추는 torch-free 음색(edge-tts → ONNX). 개인용과 <b>100% 동일한</b>
    음성을 원하면 아래 업그레이드를 누르세요 — 이 컴퓨터에 설치되며 수 분 걸립니다.
  </p>
  <div class="vp-modes">
    <label><input type="radio" name="vmode" value="pocket" checked>
      Pocket — 개인용 <b>기본</b> 음성(영어 자비스, 그대로) · HF 토큰 1회 필요</label>
    <label><input type="radio" name="vmode" value="rvc">
      RVC — 한국어 음색(torch, 무거움 · 고급)</label>
  </div>
  <button id="btnUpgrade" class="btn-upgrade">개인용 풀음성으로 업그레이드</button>
  <pre id="vpLog" class="vp-log"></pre>
</div>

<script>
(function () {
  const cards = document.querySelectorAll('.card');
  const keySection = document.getElementById('keySection');
  const keyLabel = document.getElementById('keyLabel');
  const keyInput = document.getElementById('keyInput');
  const btnStart = document.getElementById('btnStart');
  const msgEl = document.getElementById('msg');
  const doneBox = document.getElementById('doneBox');

  const KEY_LABELS = {
    gemini: 'Google AI Studio API 키',
  };

  function selectedProvider() {
    const checked = document.querySelector('input[name="provider"]:checked');
    return checked ? checked.value : 'claude';
  }

  const loginSection = document.getElementById('loginSection');
  const btnLogin = document.getElementById('btnLogin');
  const loginStatus = document.getElementById('loginStatus');
  const OAUTH = { claude: true, gpt: true };
  let loginState = { claude: false, gpt: false };
  let pollTimer = null;

  function updateUI() {
    const prov = selectedProvider();
    cards.forEach(c => c.classList.toggle('selected', c.dataset.provider === prov));
    const needsKey = prov === 'gemini';
    keySection.classList.toggle('visible', needsKey);
    loginSection.style.display = OAUTH[prov] ? 'block' : 'none';
    if (needsKey) {
      keyLabel.textContent = KEY_LABELS[prov] || 'API 키';
      keyInput.placeholder = '키를 여기에 붙여넣으세요';
    }
    if (OAUTH[prov]) refreshLoginStatus(prov);
    msgEl.textContent = '';
    msgEl.className = '';
  }

  async function refreshLoginStatus(prov) {
    loginStatus.textContent = '로그인 상태를 확인하는 중…';
    btnLogin.style.display = 'inline-block';
    try {
      const r = await fetch('/login-status?provider=' + prov);
      const d = await r.json();
      loginState[prov] = !!d.logged_in;
    } catch (e) { loginState[prov] = false; }
    paintLogin(prov);
  }

  function paintLogin(prov) {
    if (loginState[prov]) {
      loginStatus.textContent = '✓ 로그인됨 — 바로 사용할 수 있습니다.';
      loginStatus.style.color = '#4ade80';
      btnLogin.style.display = 'none';
    } else {
      loginStatus.textContent = (prov === 'claude' ? 'Claude' : 'ChatGPT')
        + ' 로그인이 필요합니다. 아래 버튼을 누르세요.';
      loginStatus.style.color = '#7dd3fc';
      btnLogin.style.display = 'inline-block';
      btnLogin.textContent = (prov === 'claude' ? 'Claude' : 'ChatGPT') + ' 로그인';
    }
  }

  btnLogin.addEventListener('click', async () => {
    const prov = selectedProvider();
    btnLogin.disabled = true;
    loginStatus.style.color = '#7dd3fc';
    loginStatus.textContent = '브라우저를 여는 중…';
    try {
      const r = await fetch('/login', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: prov }) });
      const d = await r.json();
      loginStatus.textContent = d.message || '';
      if (!d.ok) { btnLogin.disabled = false; return; }
    } catch (e) { loginStatus.textContent = '로그인 실행 실패'; btnLogin.disabled = false; return; }
    // 완료까지 폴링 — 로그인되면 자동으로 ✓
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      try {
        const r = await fetch('/login-status?provider=' + prov);
        const d = await r.json();
        if (d.logged_in) {
          loginState[prov] = true;
          clearInterval(pollTimer); pollTimer = null;
          btnLogin.disabled = false;
          paintLogin(prov);
        }
      } catch (e) {}
    }, 2000);
  });

  cards.forEach(card => {
    card.addEventListener('click', () => {
      const radio = card.querySelector('input[type="radio"]');
      radio.checked = true;
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
      btnLogin.disabled = false;
      updateUI();
    });
  });

  btnStart.addEventListener('click', async () => {
    const prov = selectedProvider();
    const key = keyInput.value.trim();
    msgEl.textContent = '검증 중…';
    msgEl.className = '';
    btnStart.disabled = true;

    try {
      const deskEl = document.getElementById('deskShortcut');
      const vEl = document.querySelector('input[name="vchoice"]:checked');
      const nEl = document.getElementById('aiName');
      const pEl = document.getElementById('pttKey');
      const res = await fetch('/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: prov, key,
                               desktop_shortcut: deskEl ? deskEl.checked : false,
                               voice: vEl ? vEl.value : 'jarvis',
                               name: nEl ? nEl.value.trim() : '',
                               ptt_key: pEl ? pEl.value : 'alt_r' }),
      });
      const data = await res.json();
      if (data.ok) {
        if (window.__SETTINGS) {
          msgEl.textContent = '저장됐습니다 — 자비스를 재시작하면 적용됩니다. 이 창은 닫으셔도 됩니다.';
          msgEl.className = 'ok';
          btnStart.disabled = true;
        } else {
          msgEl.textContent = data.message || '성공';
          msgEl.className = 'ok';
          doneBox.classList.add('visible');
          btnStart.disabled = true;
        }
      } else {
        msgEl.textContent = data.error || '오류가 발생했습니다.';
        msgEl.className = 'fail';
        btnStart.disabled = false;
      }
    } catch (e) {
      msgEl.textContent = '서버에 연결할 수 없습니다.';
      msgEl.className = 'fail';
      btnStart.disabled = false;
    }
  });

  // --- 개인용 풀음성 업그레이드 ---
  const btnUpgrade = document.getElementById('btnUpgrade');
  const vpLog = document.getElementById('vpLog');
  let upgradeTimer = null;

  function vmode() {
    const c = document.querySelector('input[name="vmode"]:checked');
    return c ? c.value : 'pocket';
  }

  async function pollStatus() {
    try {
      const res = await fetch('/upgrade-status');
      const s = await res.json();
      if (s.log) { vpLog.textContent = s.log; vpLog.scrollTop = vpLog.scrollHeight; }
      if (s.state === 'done') {
        clearInterval(upgradeTimer); upgradeTimer = null;
        btnUpgrade.disabled = false;
        btnUpgrade.textContent = '✓ 완료 — 자비스를 재시작하세요';
      } else if (s.state === 'error') {
        clearInterval(upgradeTimer); upgradeTimer = null;
        btnUpgrade.disabled = false;
        btnUpgrade.textContent = '실패 — 다시 시도';
      }
    } catch (e) { /* keep polling */ }
  }

  if (btnUpgrade) btnUpgrade.addEventListener('click', async () => {
    btnUpgrade.disabled = true;
    btnUpgrade.textContent = '설치 중… (수 분 소요)';
    vpLog.classList.add('visible');
    vpLog.textContent = '시작하는 중…';
    try {
      const res = await fetch('/upgrade-voice', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: vmode() }),
      });
      const data = await res.json();
      if (!data.ok) {
        btnUpgrade.disabled = false;
        btnUpgrade.textContent = '개인용 풀음성으로 업그레이드';
        vpLog.textContent = data.error || '시작 실패';
        return;
      }
      if (!upgradeTimer) upgradeTimer = setInterval(pollStatus, 2000);
    } catch (e) {
      btnUpgrade.disabled = false;
      btnUpgrade.textContent = '개인용 풀음성으로 업그레이드';
      vpLog.textContent = '서버에 연결할 수 없습니다.';
    }
  });

  // 설정 모드(나중에 옵션 변경): 현재 값을 채우고 라벨을 바꾼다.
  async function applySettingsMode() {
    if (!window.__SETTINGS) return;
    const h1 = document.querySelector('h1'); const sub = document.querySelector('h1 + p');
    if (h1) h1.textContent = '자비스 설정';
    if (sub) sub.textContent = '보이스 · 마이크 키 · 두뇌 등을 바꾸고 저장하세요 (재시작 시 적용)';
    if (btnStart) btnStart.textContent = '저장';
    try {
      const r = await fetch('/current'); const c = await r.json();
      const pr = document.querySelector('input[name="provider"][value="'+c.provider+'"]');
      if (pr) pr.checked = true;
      const ve = document.querySelector('input[name="vchoice"][value="'+c.voice+'"]');
      if (ve) ve.checked = true;
      const ne = document.getElementById('aiName'); if (ne && c.name) ne.value = c.name;
      const pe = document.getElementById('pttKey'); if (pe && c.ptt_key) pe.value = c.ptt_key;
    } catch (e) {}
    updateUI();
  }

  updateUI();
  applySettingsMode();
})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# _Server
# ---------------------------------------------------------------------------

class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address) -> None:
        # 설정 페이지가 닫히거나 폴링 중 끊기면 ConnectionReset이 정상적으로 난다 —
        # 트레이스백을 로그에 토하지 않는다.
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


# ---------------------------------------------------------------------------
# SetupServer
# ---------------------------------------------------------------------------

class SetupServer:
    """브라우저 기반 첫 실행 설정 서버.

    validator(provider, key) → (ok, msg) — 비동기, 기본값은 validate.validate.
    store_save(provider, key) — 동기, 기본값은 save_setup + save_key.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        validator: Callable | None = None,
        store_save: Callable | None = None,
        upgrade_cmd: Callable[[str], list[str]] | None = None,
        shortcut_fn: Callable | None = None,
        settings_mode: bool = False,
    ) -> None:
        self._host = host
        self.port = port
        self._validator = validator or _default_validate
        self._store_save = store_save or _default_store_save
        self._upgrade_cmd = upgrade_cmd or _default_upgrade_cmd
        self._shortcut_fn = shortcut_fn or _default_shortcut
        # 설정 모드: 첫 실행이 아니라 '나중에 옵션 변경'으로 열린 경우. 현재 값을
        # 미리 채우고, 저장 후 '재시작하면 적용' 안내를 띄운다(부팅을 막지 않는다).
        self._settings_mode = settings_mode
        self.done = threading.Event()
        self.chosen: str | None = None
        self._httpd: _Server | None = None
        self._thread: threading.Thread | None = None
        # 풀음성 업그레이드 진행 상태(UI가 /upgrade-status로 폴링).
        self._upgrade: dict[str, str] = {"state": "idle", "log": ""}
        self._upgrade_lock = threading.Lock()

    # --- 개인용 풀음성 업그레이드 ------------------------------------------
    def upgrade_status(self) -> dict[str, str]:
        with self._upgrade_lock:
            return dict(self._upgrade)

    def _start_upgrade(self, mode: str) -> tuple[bool, str]:
        """업그레이드 스크립트를 백그라운드로 실행. (시작됨?, 메시지)."""
        if mode not in ("pocket", "rvc"):
            return False, "알 수 없는 음성 모드입니다."
        with self._upgrade_lock:
            if self._upgrade["state"] == "running":
                return False, "이미 설치가 진행 중입니다."
            self._upgrade = {"state": "running", "log": "시작하는 중…\n"}
        cmd = self._upgrade_cmd(mode)

        def _run() -> None:
            import subprocess
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                )
                lines: list[str] = []
                assert proc.stdout is not None
                for line in proc.stdout:
                    lines.append(line)
                    if len(lines) > 200:
                        lines = lines[-200:]
                    with self._upgrade_lock:
                        self._upgrade["log"] = "".join(lines)
                rc = proc.wait()
                with self._upgrade_lock:
                    self._upgrade["state"] = "done" if rc == 0 else "error"
                    if rc != 0:
                        self._upgrade["log"] += f"\n[종료 코드 {rc}]"
            except Exception as e:  # noqa: BLE001
                with self._upgrade_lock:
                    self._upgrade = {"state": "error", "log": f"실행 실패: {e}"}

        threading.Thread(target=_run, name="jarvis-voice-upgrade", daemon=True).start()
        return True, "started"

    @property
    def url(self) -> str:
        return f"http://{self._host}:{self.port}/"

    def start(self) -> None:
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # noqa: D102 - stderr 스팸 방지
                pass

            def _send_json(self, code: int, payload: dict) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                path = self.path.split("?", 1)[0]
                if path in ("/", "/index.html"):
                    html = SETUP_HTML
                    if outer._settings_mode:
                        # 설정 모드 플래그를 주입 — JS가 현재값 채우고 라벨을 바꾼다.
                        html = html.replace("<head>", "<head><script>window.__SETTINGS=true;</script>", 1)
                    body = html.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif path == "/current":
                    from .store import load_setup
                    try:
                        s = load_setup()
                    except Exception:  # noqa: BLE001
                        s = {}
                    self._send_json(200, {
                        "provider": s.get("brain_provider", "claude"),
                        "voice": s.get("voice", "jarvis"),
                        "name": s.get("assistant_name", "자비스"),
                        "ptt_key": s.get("ptt_key", "alt_r"),
                    })
                elif path == "/upgrade-status":
                    self._send_json(200, outer.upgrade_status())
                elif path == "/login-status":
                    from urllib.parse import parse_qs, urlparse
                    q = parse_qs(urlparse(self.path).query)
                    provider = (q.get("provider", [""])[0]).strip()
                    from .login import login_status
                    try:
                        ok = login_status(provider)
                    except Exception:  # noqa: BLE001
                        ok = False
                    self._send_json(200, {"logged_in": ok})
                else:
                    self.send_error(404)

            def do_POST(self) -> None:  # noqa: N802
                if self.path == "/login":
                    try:
                        n = int(self.headers.get("Content-Length", "0"))
                        data = json.loads(self.rfile.read(n) or b"{}")
                        provider = str(data.get("provider", "")).strip()
                    except Exception:  # noqa: BLE001
                        self._send_json(400, {"ok": False, "error": "잘못된 요청입니다."})
                        return
                    from .login import start_login
                    try:
                        ok, msg = start_login(provider)
                    except Exception:  # noqa: BLE001
                        ok, msg = False, "로그인 실행 중 오류가 났습니다."
                    self._send_json(200, {"ok": ok, "message": msg})
                    return
                if self.path == "/upgrade-voice":
                    try:
                        n = int(self.headers.get("Content-Length", "0"))
                        data = json.loads(self.rfile.read(n) or b"{}")
                        mode = str(data.get("mode", "pocket")).strip()
                    except Exception:  # noqa: BLE001
                        self._send_json(400, {"ok": False, "error": "잘못된 요청입니다."})
                        return
                    ok, msg = outer._start_upgrade(mode)
                    self._send_json(200 if ok else 409,
                                    {"ok": ok, "error": None if ok else msg})
                    return
                if self.path != "/setup":
                    self.send_error(404)
                    return
                try:
                    n = int(self.headers.get("Content-Length", "0"))
                    data = json.loads(self.rfile.read(n) or b"{}")
                    provider = str(data.get("provider", "")).strip()
                    key = str(data.get("key", "")).strip()
                    want_shortcut = bool(data.get("desktop_shortcut"))
                    voice = str(data.get("voice", "") or "jarvis").strip()
                    name = str(data.get("name", "") or "").strip()
                    ptt_key = str(data.get("ptt_key", "") or "").strip()
                except Exception:  # noqa: BLE001
                    self._send_json(400, {"ok": False, "error": "잘못된 요청입니다."})
                    return

                if not provider:
                    self._send_json(400, {"ok": False, "error": "프로바이더를 선택하세요."})
                    return

                # 설정 모드에서 키를 비워 보내면(음성/이름/키만 변경) 검증을 건너뛰고 기존 키를
                # 유지한다 — gemini/gpt 두뇌일 때 음성만 바꾸려 해도 키 재입력을 강요하던 것 수정
                # (audit medium). save_key는 빈 키를 무시하므로 기존 키가 보존된다.
                if outer._settings_mode and not key:
                    try:
                        try:
                            outer._store_save(provider, key, voice=voice, name=name,
                                              ptt_key=ptt_key)
                        except TypeError:
                            try:
                                outer._store_save(provider, key, voice=voice, name=name)
                            except TypeError:
                                outer._store_save(provider, key)
                    except Exception:  # noqa: BLE001
                        self._send_json(500, {"ok": False, "error": "설정 저장 중 오류가 났습니다."})
                        return
                    outer.chosen = provider
                    outer.done.set()
                    self._send_json(200, {"ok": True,
                                          "message": "설정을 저장했습니다. 재시작하면 적용됩니다."})
                    return

                try:
                    ok, msg = asyncio.run(outer._validator(provider, key))
                except Exception:  # noqa: BLE001
                    self._send_json(500, {"ok": False, "error": "검증 중 오류가 났습니다."})
                    return

                if ok:
                    try:
                        try:
                            outer._store_save(provider, key, voice=voice, name=name,
                                              ptt_key=ptt_key)
                        except TypeError:
                            # 구형 시그니처 호환(ptt_key/voice/name 미지원 콜백)
                            try:
                                outer._store_save(provider, key, voice=voice, name=name)
                            except TypeError:
                                outer._store_save(provider, key)
                    except Exception:  # noqa: BLE001
                        self._send_json(500, {"ok": False, "error": "설정 저장 중 오류가 났습니다."})
                        return
                    if want_shortcut:
                        try:
                            s_ok, s_msg = outer._shortcut_fn()
                            if s_msg:
                                msg = f"{msg} · {s_msg}"
                        except Exception:  # noqa: BLE001 - 바로가기는 옵션, 실패해도 진행
                            pass
                    outer.chosen = provider
                    outer.done.set()
                    self._send_json(200, {"ok": True, "message": msg})
                else:
                    self._send_json(200, {"ok": False, "error": msg})

        self._httpd = _Server((self._host, self.port), _Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="jarvis-setup", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


# ---------------------------------------------------------------------------
# 기본 store_save 구현
# ---------------------------------------------------------------------------

def _default_store_save(provider: str, key: str, *,
                        voice: str | None = None, name: str | None = None,
                        ptt_key: str | None = None) -> None:
    save_setup(provider, voice=voice, name=name, ptt_key=ptt_key)
    if key:
        save_key(provider, key)


def _default_upgrade_cmd(mode: str) -> list[str]:
    """풀음성 업그레이드 스크립트 실행 커맨드.

    프로즌 번들이면 JARVIS_BUNDLE_ROOT(launcher가 export)에 스크립트가 있고,
    dev면 repo의 packaging/ 에 있다. 플랫폼별로 bash(.sh) / powershell(.ps1).
    """
    bundle = os.environ.get("JARVIS_BUNDLE_ROOT")
    repo_pkg = Path(__file__).resolve().parents[2] / "packaging"
    base = Path(bundle) if bundle else repo_pkg
    if sys.platform.startswith("win"):
        script = base / "upgrade_full_voice.ps1"
        return ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script),
                "-Mode", mode]
    script = base / "upgrade_full_voice.sh"
    return ["bash", str(script), "--mode", mode]
