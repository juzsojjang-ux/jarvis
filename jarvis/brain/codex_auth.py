"""ChatGPT 구독(Codex) 토큰 — codex login이 ~/.codex/auth.json에 저장한 OAuth
토큰을 읽고 만료 시 갱신한다. 비공식 경로(엔드포인트가 바뀔 수 있음). 토큰은
비밀번호처럼 취급 — 절대 로그에 찍지 않는다."""
from __future__ import annotations
import base64, json, os, time
from pathlib import Path
from typing import Any, Optional

CODEX_AUTH_PATH = Path.home() / ".codex" / "auth.json"
_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"


def _read(path: Path) -> Optional[dict]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _fields(auth: dict) -> dict:
    # 평면 또는 tokens.{} 중첩 양쪽 지원
    t = auth.get("tokens") if isinstance(auth.get("tokens"), dict) else auth
    return {
        "access_token": t.get("access_token") or auth.get("access_token"),
        "refresh_token": t.get("refresh_token") or auth.get("refresh_token"),
        "expires": auth.get("expires") or t.get("expires"),
        "accountId": t.get("accountId") or auth.get("accountId") or auth.get("account_id"),
    }


def load_codex_auth(path: Path | None = None) -> Optional[dict]:
    raw = _read(Path(path) if path else CODEX_AUTH_PATH)
    if not raw:
        return None
    f = _fields(raw)
    return f if f.get("access_token") else None


def is_codex_logged_in(path: Path | None = None) -> bool:
    return load_codex_auth(path) is not None


def _account_id_from(f: dict) -> str:
    if f.get("accountId"):
        return str(f["accountId"])
    tok = f.get("access_token") or ""
    try:
        payload = tok.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        auth = data.get("https://api.openai.com/auth", {})
        return str(auth.get("chatgpt_account_id", "")) or ""
    except Exception:  # noqa: BLE001
        return ""


async def get_access(path: Path | None = None, now_ms: int | None = None,
                     http: Any = None) -> tuple[str, str]:
    """(access_token, account_id). 만료 시 refresh 후 파일 갱신. 미로그인이면 RuntimeError."""
    p = Path(path) if path else CODEX_AUTH_PATH
    f = load_codex_auth(p)
    if f is None:
        raise RuntimeError("ChatGPT 구독을 쓰려면 먼저 `codex login` 을 실행하세요.")
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    expires = f.get("expires")
    if expires is not None and int(expires) <= now + 60_000 and f.get("refresh_token"):
        token, expires2 = await _refresh(f["refresh_token"], http)
        if token:
            f["access_token"] = token
            f["expires"] = expires2
            _save(p, f)
    return f["access_token"], _account_id_from(f)


async def _refresh(refresh_token: str, http: Any) -> tuple[Optional[str], Optional[int]]:
    try:
        client = http
        close = False
        if client is None:
            import httpx
            client = httpx.AsyncClient(timeout=20)
            close = True
        try:
            r = await client.post(_OAUTH_TOKEN_URL, json={
                "grant_type": "refresh_token", "refresh_token": refresh_token,
                "client_id": _CLIENT_ID})
            data = r.json()
        finally:
            if close:
                await client.aclose()
        access = data.get("access_token")
        expires_in = data.get("expires_in")
        exp_ms = (int(time.time() * 1000) + int(expires_in) * 1000) if expires_in else None
        return access, exp_ms
    except Exception:  # noqa: BLE001 - 갱신 실패 시 기존 토큰으로 시도
        return None, None


def _save(path: Path, fields: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(fields, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001
        pass
