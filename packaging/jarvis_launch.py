"""PyInstaller entry-point shim for JARVIS (distributable).

배포 번들은 기본적으로 torch-free 음성(edge-tts → ONNX RVC)을 쓴다 — 가볍고 안 멈춘다.
다만 사용자가 셋업 UI에서 '개인용 풀음성으로 업그레이드'를 실행하면 ~/.jarvis/voice_full.json
마커가 생기고, 그때는 개인용과 동일한 Pocket / MeloTTS+RVC 체인을 켠다(하이브리드).

순서:
  1) 풀음성 마커가 유효하면 그 JARVIS_* env를 먼저 적용(개인용 동일 음성).
  2) 아니면 torch-free 기본값(edge/onnx) 강제.
사용자가 직접 지정한 env(JARVIS_*)는 둘 다 setdefault라 항상 우선.

dev(`python -m jarvis`)는 이 파일을 안 거쳐 현 설정(Pocket) 유지."""
import multiprocessing
import os
import sys
from pathlib import Path

# frozen 번들에서 multiprocessing 워커가 진입 스크립트를 재실행하는 것을 막는다.
# (없으면 모델 다운로드 등에서 워커가 _amain을 다시 돌려 '이미 실행 중'을 띄움)
multiprocessing.freeze_support()

# --- 0) 자식 역할 디스패치 (--child=jarvis.hud.tray 등) --------------------------
# frozen 번들에서 본체가 오버레이/트레이를 띄울 때 자기 자신(JARVIS.exe)을 이
# 플래그로 재실행한다. 본체 부팅 코드보다 반드시 먼저 처리해야 한다 — 안 그러면
# 자식마다 본체가 통째로 또 떠 무한 증식한다(__main__._child_cmd 참조).
_ALLOWED_CHILDREN = {"jarvis.hud.overlay_mac", "jarvis.hud.overlay_win", "jarvis.hud.tray"}
if len(sys.argv) >= 2 and sys.argv[1].startswith("--child="):
    _mod = sys.argv[1].split("=", 1)[1]
    if _mod not in _ALLOWED_CHILDREN:
        sys.exit(2)
    import runpy

    sys.argv = [_mod, *sys.argv[2:]]
    runpy.run_module(_mod, run_name="__main__")
    sys.exit(0)

# --- 0b) 설정 변경 모드 (트레이 '설정' → JARVIS --settings) -----------------------
# 실행 중인 자비스 본체를 건드리지 않고, 별도로 설정 UI만 띄워 setup.json을 고친다.
if len(sys.argv) >= 2 and sys.argv[1] == "--settings":
    from jarvis.setup.launcher import run_settings
    run_settings()
    sys.exit(0)

# --- 1) 설정에서 고른 보이스 프리셋을 먼저 적용 ---------------------------------
# 명시적으로 고른 음성(jarvis_ko/female_us 등)이 마커·기본값보다 우선해야 한다 — 전부
# setdefault라 먼저 적용한 것이 이긴다. 'jarvis'(기본 Pocket 체인) 프리셋은 빈 dict라
# 아무것도 set하지 않으므로, 그때만 아래 마커가 음색을 정한다. (예전엔 마커가 먼저라
# 프리셋 선택이 무시되던 버그)
_voice_preset = "jarvis"
try:
    from jarvis.setup.store import apply_setup_env, load_setup
    _voice_preset = (load_setup() or {}).get("voice", "jarvis")
    apply_setup_env()
except Exception:  # noqa: BLE001 - 설정 적용 실패가 부팅을 막으면 안 된다
    pass

# --- 2) 개인용 풀음성 마커는 보이스가 'jarvis'(기본 Pocket 체인)일 때만 적용 --------
_FULL_VOICE = False
if _voice_preset == "jarvis":
    try:
        from jarvis.core.voice_full import apply_voice_full
        _FULL_VOICE = apply_voice_full()  # ~/.jarvis/voice_full.json 유효 시 env 주입
    except Exception:  # noqa: BLE001 - 마커 처리 실패가 부팅을 막으면 안 된다
        _FULL_VOICE = False

# --- 3) 그래도 미정이면 torch-free 기본값(edge/onnx). setdefault라 위에서 정해졌으면 유지 ---
os.environ.setdefault("JARVIS_TTS_BACKEND", "edge")
os.environ.setdefault("JARVIS_VC_BACKEND", "onnx")
os.environ.setdefault("JARVIS_REPLY_LANGUAGE", "en")

# 프로즌 번들에서는 모델 파일이 ~/jarvis가 아니라 _MEIPASS/voice_models에 있다.
# config의 절대경로 기본값을 번들 경로로 덮어쓴다(사용자 env가 있으면 유지).
# VAD(웨이크워드)·ONNX 음색 모델은 풀음성 여부와 무관하게 번들 경로를 기본으로 둔다
# (풀음성 마커가 TTS/VC를 명시적으로 덮으면 ONNX 경로는 그냥 안 쓰일 뿐).
_meipass = getattr(sys, "_MEIPASS", None)
if _meipass:
    _vm = Path(_meipass) / "voice_models"
    os.environ.setdefault("JARVIS_ONNX_MODEL_PATH", str(_vm / "jarvis.onnx"))
    os.environ.setdefault("JARVIS_ONNX_CONTENTVEC_PATH", str(_vm / "vec-768-layer-12.onnx"))
    os.environ.setdefault("JARVIS_VAD_MODEL_PATH", str(_vm / "silero_vad.onnx"))
    # 풀음성 업그레이드 스크립트/소스/자산이 번들 어디에 있는지 셋업 UI에 알려준다.
    os.environ.setdefault("JARVIS_BUNDLE_ROOT", str(Path(_meipass)))

# --- 3) Windows frozen: sounddevice WinError 50 가드 ---------------------------
# sounddevice는 import 시 PortAudio 초기화 동안 os.dup/dup2로 stderr(fd 2)를
# /dev/null로 돌린다. PyInstaller 윈도우 번들에서는 이게 CRT 핸들 상속 테이블을
# 망가뜨려 이후 모든 subprocess 실행이 WinError 50으로 죽는다(Claude CLI 포함;
# spatialaudio/python-sounddevice#461, 미수정). _initialize()는 os.dup이
# OSError를 던지면 리다이렉트 전체를 건너뛰도록 짜여 있으므로, frozen 윈도우에서
# 첫 import 동안만 os.dup을 막아 그 안전 경로를 태운다.
if os.name == "nt" and getattr(sys, "frozen", False):
    _real_dup = os.dup

    def _no_dup(fd):  # noqa: ANN001
        raise OSError("jarvis: skip stderr redirect in frozen app (WinError 50 guard)")

    os.dup = _no_dup
    try:
        import sounddevice  # noqa: F401 - 가드 아래에서 PortAudio 초기화
    except Exception:  # noqa: BLE001 - 오디오 초기화 실패가 부팅 자체를 막으면 안 된다
        pass
    finally:
        os.dup = _real_dup

# --- 4) 배포판 로그/크래시 기록 ------------------------------------------------
# 더블클릭 실행은 죽는 순간 콘솔이 닫혀 원인을 볼 수 없다. 모든 출력을
# ~/.jarvis/logs/jarvis.log 로 복제하고, 크래시 트레이스백은 crash.log 에 남긴 뒤
# Windows에서는 Enter를 기다려 창이 바로 닫히지 않게 한다.
_LOG_DIR = Path.home() / ".jarvis" / "logs"


class _Tee:
    def __init__(self, stream, logfile):
        self._stream = stream
        self._log = logfile

    def write(self, text):
        try:
            if self._stream:
                self._stream.write(text)
        except Exception:  # noqa: BLE001 - 콘솔 인코딩 실패가 로그를 막으면 안 된다
            pass
        try:
            self._log.write(text)
        except Exception:  # noqa: BLE001
            pass

    def flush(self):
        for s in (self._stream, self._log):
            try:
                if s:
                    s.flush()
            except Exception:  # noqa: BLE001
                pass

    def fileno(self):
        # 진짜 fd가 필요한 경우(예: subprocess.Popen(stderr=sys.stderr)로 Pocket/Melo/RVC
        # 워커를 띄울 때)를 위해 밑단 fd를 내준다. _Tee에 fileno가 없으면 워커 spawn이
        # '_Tee has no attribute fileno'로 죽어 배포 앱 Pocket 음성이 통째로 먹통이 된다.
        # 원본 stderr가 없으면(GUI .app는 None일 수 있다) 로그파일 fd로 폴백 — 워커
        # stderr가 사라지지 않게.
        for s in (self._stream, self._log):
            try:
                if s is not None:
                    return s.fileno()
            except (OSError, ValueError, AttributeError):
                continue
        raise OSError("jarvis _Tee: 사용할 수 있는 fileno가 없습니다")


def _install_dist_logging():
    import faulthandler

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    run_log = open(_LOG_DIR / "jarvis.log", "a", encoding="utf-8", errors="replace", buffering=1)
    import datetime

    run_log.write(f"\n=== JARVIS start {datetime.datetime.now().isoformat()} ===\n")
    sys.stdout = _Tee(sys.__stdout__, run_log)
    sys.stderr = _Tee(sys.__stderr__, run_log)
    crash_log = open(_LOG_DIR / "crash.log", "a", encoding="utf-8", errors="replace", buffering=1)
    faulthandler.enable(crash_log)
    return crash_log


from jarvis.__main__ import main

if __name__ == "__main__":
    _crash_log = _install_dist_logging()
    try:
        main()
    except SystemExit:
        raise
    except BaseException:
        import datetime
        import traceback

        _crash_log.write(f"\n=== CRASH {datetime.datetime.now().isoformat()} ===\n")
        traceback.print_exc(file=_crash_log)
        traceback.print_exc()
        print(f"\n[JARVIS] 오류로 종료됐습니다. 로그: {_LOG_DIR}")
        if os.name == "nt":
            try:
                input("Enter 를 누르면 창이 닫힙니다...")
            except Exception:  # noqa: BLE001 - 콘솔 없는 환경(pythonw)에서는 그냥 종료
                pass
        raise
