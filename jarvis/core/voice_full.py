"""개인용 '풀음성' 업그레이드 마커 로더.

배포 번들은 기본적으로 torch-free 음성(edge-tts → ONNX RVC)을 쓴다. 사용자가
셋업 UI에서 '개인용 풀음성으로 업그레이드'를 실행하면, packaging/upgrade_full_voice
스크립트가 ~/.jarvis/voice-full/ 에 torch venv(Pocket / MeloTTS+RVC)를 깔고
``~/.jarvis/voice_full.json`` 마커를 남긴다.

이 모듈은 그 마커를 읽어 **개인용과 동일한 음성 체인을 켜는 JARVIS_* 환경변수**를
돌려준다. launcher(jarvis_launch.py)가 프로즌 번들에서 edge/onnx 기본값을 강제하기
전에 이걸 먼저 확인해서, 마커가 살아있으면 풀음성 env를 적용한다.

마커가 없거나(미설치) 가리키는 venv/모델 경로가 사라졌으면(손상) None을 돌려줘
launcher가 torch-free 기본값으로 안전하게 폴백하게 한다. — 즉 업그레이드는
'있으면 켜지고, 깨지면 조용히 원래대로'가 보장된다.

마커 스키마(upgrade 스크립트가 작성):
    {
      "version": 1,
      "mode": "pocket" | "melotts_rvc",
      "env": { "JARVIS_TTS_BACKEND": "pocket", ... },   # 그대로 환경변수로 주입
      "verify_paths": ["/abs/venv/bin/python", "/abs/models/jarvis.pth"]
    }
``verify_paths`` 중 하나라도 실제로 없으면 마커를 무효로 본다.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

# 마커 기본 위치 — ~/jarvis(소스 repo)가 아니라 사용자 홈의 ~/.jarvis 아래.
DEFAULT_MARKER_PATH = Path.home() / ".jarvis" / "voice_full.json"


def load_voice_full(
    path: str | os.PathLike[str] = DEFAULT_MARKER_PATH,
    *,
    exists: Callable[[str], bool] = os.path.exists,
) -> dict[str, str] | None:
    """풀음성 마커가 유효하면 주입할 ``JARVIS_*`` env dict, 아니면 None.

    ``exists``는 테스트 주입용(verify_paths 검증을 가짜 파일시스템으로).
    어떤 이유로든(파일 없음/JSON 깨짐/env 누락/경로 검증 실패) 실패하면 None —
    절대 예외를 올리지 않는다. 음성 업그레이드 마커가 부팅을 막으면 안 되니까.
    """
    p = Path(os.path.expanduser(str(path)))
    try:
        if not p.is_file():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    env = data.get("env")
    if not isinstance(env, dict) or not env:
        return None
    # 값은 전부 문자열이어야 환경변수로 주입 가능.
    env_str: dict[str, str] = {}
    for k, v in env.items():
        if not isinstance(k, str) or v is None:
            return None
        env_str[k] = str(v)

    # 가리키는 venv/모델이 실제로 존재하는지 — 하나라도 없으면 무효(미설치/손상).
    for vp in data.get("verify_paths", []) or []:
        if not isinstance(vp, str) or not exists(os.path.expanduser(vp)):
            return None

    return env_str


def apply_voice_full(
    environ: dict[str, str] | None = None,
    *,
    path: str | os.PathLike[str] = DEFAULT_MARKER_PATH,
    exists: Callable[[str], bool] = os.path.exists,
) -> bool:
    """풀음성 마커가 유효하면 그 env를 ``environ``에 setdefault하고 True 반환.

    setdefault라서 사용자가 직접 지정한 JARVIS_* 환경변수가 항상 우선한다.
    True를 반환하면 launcher는 edge/onnx 기본값 강제를 건너뛴다.
    """
    target = os.environ if environ is None else environ
    full = load_voice_full(path, exists=exists)
    if not full:
        return False
    for k, v in full.items():
        target.setdefault(k, v)
    return True
