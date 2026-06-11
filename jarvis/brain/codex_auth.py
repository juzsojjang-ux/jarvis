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
    # 평면 또는 tokens.{} 중첩 양쪽 지원. 실제 codex 파일은 tokens.account_id(snake).
    t = auth.get("tokens") if isinstance(auth.get("tokens"), dict) else auth
    return {
        "access_token": t.get("access_token") or auth.get("access_token"),
        "refresh_token": t.get("refresh_token") or auth.get("refresh_token"),
        "expires": auth.get("expires") or t.get("expires"),
        "accountId": (t.get("accountId") or t.get("account_id")
                      or auth.get("accountId") or auth.get("account_id")),
        "last_refresh": auth.get("last_refresh") or t.get("last_refresh"),
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


_REFRESH_AFTER_S = 8 * 24 * 3600  # last_refresh가 8일 넘으면 선제 갱신(토큰 수명 ~10일)


def _stale(f: dict, now_ms: int) -> bool:
    """expires(ms) 또는 last_refresh(ISO) 기준으로 곧 만료인지. 정보 없으면 갱신 쪽."""
    expires = f.get("expires")
    if expires is not None:
        try:
            return int(expires) <= now_ms + 60_000
        except (TypeError, ValueError):
            pass
    lr = f.get("last_refresh")
    if lr:
        try:
            import datetime as _dt
            ts = _dt.datetime.fromisoformat(str(lr).replace("Z", "+00:00"))
            age = now_ms / 1000 - ts.timestamp()
            return age >= _REFRESH_AFTER_S
        except Exception:  # noqa: BLE001
            return True
    return True  # 만료 정보가 전혀 없으면 갱신 시도


async def get_access(path: Path | None = None, now_ms: int | None = None,
                     http: Any = None, force: bool = False) -> tuple[str, str]:
    """(access_token, account_id). 만료(또는 force) 시 refresh 후 파일에 구조 보존
    저장. 미로그인이면 RuntimeError. 호출부는 401 시 force=True로 재시도하면 된다."""
    p = Path(path) if path else CODEX_AUTH_PATH
    raw = _read(p)
    f = load_codex_auth(p)
    if f is None or raw is None:
        raise RuntimeError("ChatGPT 구독을 쓰려면 먼저 `codex login` 을 실행하세요.")
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    if (force or _stale(f, now)) and f.get("refresh_token"):
        data = await _refresh(f["refresh_token"], http)
        if data and data.get("access_token"):
            _apply_refresh(raw, data, now)
            _save(p, raw)
            f = _fields(raw)
    return f["access_token"], _account_id_from(f)


def _apply_refresh(raw: dict, data: dict, now_ms: int) -> None:
    """갱신 토큰을 raw 구조(평면/tokens 중첩) 제자리에 써넣는다 — codex CLI 호환 유지."""
    import datetime as _dt
    target = raw["tokens"] if isinstance(raw.get("tokens"), dict) else raw
    if data.get("access_token"):
        target["access_token"] = data["access_token"]
    if data.get("refresh_token"):
        target["refresh_token"] = data["refresh_token"]
    if data.get("id_token"):
        target["id_token"] = data["id_token"]
    raw["last_refresh"] = _dt.datetime.fromtimestamp(
        now_ms / 1000, _dt.timezone.utc).isoformat()
    if "expires" in raw and data.get("expires_in"):
        raw["expires"] = now_ms + int(data["expires_in"]) * 1000


async def _refresh(refresh_token: str, http: Any) -> Optional[dict]:
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
            return r.json()
        finally:
            if close:
                await client.aclose()
    except Exception:  # noqa: BLE001 - 갱신 실패 시 기존 토큰으로 시도
        return None


def _save(path: Path, raw: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:  # noqa: BLE001
        pass
