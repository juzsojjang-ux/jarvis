# JARVIS Phase 1 · M2 — JARVIS Voice + Training Route Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 임시 음성을 실제 자비스 음색 한국어로 교체: MeloTTS-KR(발음) → RVC(음색). 더불어 자비스 음성 학습 루트(자동 수집→전처리→Colab RVC 학습→.pth 장착).

**Architecture:** 2-프로세스(메인 + .venv-tts MeloTTS 워커, IPC), TTS→VC 체인. voice_training/는 오프라인 배치(수집·분리·세그먼트·정리·리샘플) + Colab 학습.

**Tech Stack:** MeloTTS, python-mecab-ko, mlx-rvc(+PyTorch-MPS 포크 폴백), faiss-cpu>=1.7.2, audio-separator==0.44.2, yt-dlp, ffmpeg, noisereduce

**Spec:** `docs/superpowers/specs/2026-06-09-jarvis-voice-assistant-design.md`

---

## Milestone 2: JARVIS Voice + Training Route

**Goal:** Replace the M1 placeholder voice with a real, locally-running JARVIS-timbre Korean voice: MeloTTS-KR (correct Korean pronunciation, 44100 Hz) over a `.venv-tts` worker IPC + RVC (JARVIS timbre) conversion, plus the offline `voice_training/` pipeline (yt-dlp → BS-Roformer → silence-split → denoise → 40 kHz) that produces the RVC `.pth`+`.index` on Colab.

**API signatures confirmed via WebSearch/WebFetch before coding** (mlx-rvc README, audio-separator PyPI, MeloTTS docs, noisereduce, yt-dlp, soundfile): `from melo.api import TTS; TTS(language="KR", device="cpu"); model.hps.data.spk2id["KR"]; model.tts_to_file(text, spk, out, speed=1.0)` (44100 Hz); `from audio_separator.separator import Separator; Separator(output_dir=, model_file_dir=, output_format="WAV").load_model(model_filename="model_bs_roformer_ep_317_sdr_12.9755.ckpt").separate(path)->list[str]`; `audio-separator --env_info`; `mlx-rvc convert <in> <out> --model <pth> --index <index> --index-rate <r> --f0-method rmvpe --pitch <n>` (uv pip install mlx-rvc); `noisereduce.reduce_noise(y=, sr=, prop_decrease=, stationary=)`; `yt-dlp -x --audio-format wav --audio-quality 0 -o <tmpl> URL`; `soundfile==0.13.1` `sf.read(p, dtype="float32")` / `sf.write(p, data, sr)`. The mlx-rvc Python API is niche/unstable, so `RVCConversion` shells out to the **stable CLI** (with the PyTorch-MPS fork as a drop-in `rvc_cmd` swap).

**Acceptance criteria:**
- [ ] `voice_training/` pipeline modules (`fetch`, `separate`, `segment`, `clean`, `resample`, `build_dataset`) all unit-tested green; `train_colab.ipynb` + `README.md` document run order and RVC dataset targets (10–30 min clean, 150–300 epochs, batch 40).
- [ ] `jarvis/tts/melotts_kr.py` talks to a persistent `.venv-tts` worker over `jarvis/tts/ipc.py`, returns 44100 Hz float32 — proven end-to-end against a hermetic fake worker (no MeloTTS needed in CI).
- [ ] MeCab/MeloTTS install recipe runs; Korean smoke test prints `sr=44100` and produces intelligible Korean audio.
- [ ] `jarvis/vc/rvc.py` builds the exact `mlx-rvc` command, resamples 44.1k→40k ingest and model-rate→target via `jarvis.audio.util.resample`, RMVPE f0; convert proven against a fake RVC binary.
- [ ] `faiss-cpu>=1.7.2` installs from the `.[voice]` extra (`brew install swig` present); config-driven `make_tts`/`make_vc` (called at the `build_orchestrator` DI site, NOT in `Orchestrator.__init__`) select MeloTTSKR + RVCConversion, with the RVC→NullVC bootstrap fallback when `jarvis.pth` is absent.
- [ ] Latency measured on M4 Pro 24 GB and recorded.

---

### Task 1: `voice_training/fetch.py` — yt-dlp from curated URL list (share-list gate + copyright + auto-delete)

**Files:**
- Create: `~/jarvis/voice_training/__init__.py` (empty)
- Create: `~/jarvis/voice_training/fetch.py`
- Create: `~/jarvis/voice_training/urls.example.txt`
- Create/Modify: `~/jarvis/conftest.py` (repo-root sys.path bootstrap so the top-level `voice_training` package imports in tests)
- Test: `~/jarvis/tests/voice_training/test_fetch.py`

- [ ] **Step 1: Ensure `voice_training` is importable.** Create `~/jarvis/voice_training/__init__.py` (empty). If `~/jarvis/conftest.py` does **not** exist, create it with exactly:
  ```python
  import os, sys
  sys.path.insert(0, os.path.dirname(__file__))
  ```
  If it already exists, append those two lines (idempotent). This puts the repo root on `sys.path` so `import voice_training` works regardless of the editable-install package list.

- [ ] **Step 2: Write the failing test.** Create `~/jarvis/tests/voice_training/test_fetch.py`:
  ```python
  from pathlib import Path
  import pytest
  from voice_training import fetch


  def test_load_urls_ignores_comments_and_blanks(tmp_path):
      p = tmp_path / "urls.txt"
      p.write_text("# header\n\nhttps://a/1\n  https://b/2  \n# tail\n", encoding="utf-8")
      assert fetch.load_urls(p) == ["https://a/1", "https://b/2"]


  def test_build_ytdlp_command_exact_flags(tmp_path):
      cmd = fetch.build_ytdlp_command("https://x/zzz", tmp_path)
      assert cmd == [
          "yt-dlp", "-x", "--audio-format", "wav", "--audio-quality", "0",
          "--no-playlist", "-o", str(tmp_path / "%(id)s.%(ext)s"), "https://x/zzz",
      ]


  def test_print_share_list_lists_every_url():
      msg = fetch.print_share_list(["https://a/1", "https://b/2"])
      assert "2 URLs" in msg and "https://a/1" in msg and "https://b/2" in msg


  def test_fetch_all_refuses_without_confirmation(tmp_path):
      with pytest.raises(RuntimeError):
          fetch.fetch_all(["https://a/1"], tmp_path, confirmed=False)


  def test_fetch_all_runs_ytdlp_per_url_when_confirmed(tmp_path):
      calls = []
      def fake_runner(cmd, check):
          calls.append(cmd)
          out = cmd[cmd.index("-o") + 1].replace("%(id)s", "vid").replace("%(ext)s", "wav")
          Path(out).write_bytes(b"RIFF")
      out = fetch.fetch_all(["https://a/1"], tmp_path, confirmed=True, runner=fake_runner)
      assert len(calls) == 1 and calls[0][0] == "yt-dlp" and out[0].endswith(".wav")
  ```

- [ ] **Step 3: Run & show expected FAIL.** `cd ~/jarvis && python -m pytest tests/voice_training/test_fetch.py -q` → **FAILS** with `ModuleNotFoundError: No module named 'voice_training.fetch'`.

- [ ] **Step 4: Minimal implementation.** Create `~/jarvis/voice_training/fetch.py`:
  ```python
  """Fetch JARVIS reference audio from a curated URL list using yt-dlp.

  COPYRIGHT / PRIVACY POLICY (read before running):
    - Personal, local, on-device voice-model training ONLY. No redistribution
      of downloaded audio or the resulting model.
    - You MUST review and approve the URL list (share-list-before-bulk):
      print print_share_list(urls) and pass confirmed=True only after a human
      has eyeballed it.
    - Raw downloads are auto-deleted after the dataset is built (delete_raws()).
  """
  from __future__ import annotations
  import shutil
  import subprocess
  from pathlib import Path


  def load_urls(path) -> list[str]:
      urls: list[str] = []
      for raw in Path(path).read_text(encoding="utf-8").splitlines():
          line = raw.strip()
          if not line or line.startswith("#"):
              continue
          urls.append(line)
      return urls


  def build_ytdlp_command(url: str, out_dir) -> list[str]:
      out_tmpl = str(Path(out_dir) / "%(id)s.%(ext)s")
      return ["yt-dlp", "-x", "--audio-format", "wav", "--audio-quality", "0",
              "--no-playlist", "-o", out_tmpl, url]


  def print_share_list(urls: list[str]) -> str:
      lines = ["SHARE THIS URL LIST FOR APPROVAL BEFORE BULK DOWNLOAD:",
               f"  ({len(urls)} URLs, personal/local training only, no redistribution)"]
      for i, u in enumerate(urls, 1):
          lines.append(f"  {i:>3}. {u}")
      return "\n".join(lines)


  def fetch_all(urls, out_dir, confirmed: bool, runner=subprocess.run) -> list[str]:
      if not confirmed:
          raise RuntimeError(
              "Refusing bulk download: review print_share_list(urls) and pass "
              "confirmed=True only after the URL list is approved.")
      out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
      for url in urls:
          runner(build_ytdlp_command(url, out), check=True)
      return [str(w) for w in sorted(out.glob("*.wav"))]


  def delete_raws(out_dir) -> None:
      raw = Path(out_dir)
      if raw.exists():
          shutil.rmtree(raw)
  ```
  Create `~/jarvis/voice_training/urls.example.txt`:
  ```
  # One source URL per line. '#' = comment. Personal/local training only.
  # Share this exact list for approval BEFORE bulk download (fetch.print_share_list).
  # https://www.youtube.com/watch?v=EXAMPLE_JARVIS_VOICE_CLIP
  ```

- [ ] **Step 5: Run & show expected PASS.** `cd ~/jarvis && python -m pytest tests/voice_training/test_fetch.py -q` → **5 passed**.

- [ ] **Step 6: Commit.** `cd ~/jarvis && git add -A && git commit -m "M2: voice_training fetch (yt-dlp, share-list gate, copyright/auto-delete)"`

---

### Task 2: `voice_training/separate.py` — audio-separator BS-Roformer (CoreML) + `--env_info` gate + demucs-mlx fallback

**Files:**
- Create: `~/jarvis/voice_training/separate.py`
- Test: `~/jarvis/tests/voice_training/test_separate.py`

- [ ] **Step 1: Write the failing test.** Create `~/jarvis/tests/voice_training/test_separate.py`:
  ```python
  import pytest
  from voice_training import separate


  class _R:
      def __init__(self, out): self.stdout, self.stderr = out, ""


  def test_check_env_detects_coreml():
      r = _R("providers: ['CoreMLExecutionProvider', 'CPUExecutionProvider']")
      assert separate.check_env(runner=lambda *a, **k: r) is True


  def test_check_env_false_when_cpu_only():
      r = _R("providers: ['CPUExecutionProvider']")
      assert separate.check_env(runner=lambda *a, **k: r) is False


  def test_pick_vocal_stem_selects_vocals():
      files = ["/out/song_(Instrumental)_m.wav", "/out/song_(Vocals)_m.wav"]
      assert separate.pick_vocal_stem(files).endswith("(Vocals)_m.wav")


  def test_pick_vocal_stem_raises_when_absent():
      with pytest.raises(ValueError):
          separate.pick_vocal_stem(["/out/song_(Instrumental).wav"])
  ```

- [ ] **Step 2: Run & show expected FAIL.** `cd ~/jarvis && python -m pytest tests/voice_training/test_separate.py -q` → **FAILS** `ModuleNotFoundError: voice_training.separate`.

- [ ] **Step 3: Minimal implementation.** Create `~/jarvis/voice_training/separate.py`:
  ```python
  """Vocal isolation with audio-separator (BS-Roformer, CoreML on Apple Silicon).

  Primary model: model_bs_roformer_ep_317_sdr_12.9755.ckpt via
  CoreMLExecutionProvider. Fallback (if CoreML/Roformer fails): demucs-mlx
  (`uv pip install demucs-mlx`; `python -m demucs_mlx --two-stems vocals in.wav`).
  Always gate with check_env() first (verify CoreMLExecutionProvider).
  """
  from __future__ import annotations
  import subprocess
  from pathlib import Path

  ROFORMER_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"


  def check_env(runner=subprocess.run) -> bool:
      res = runner(["audio-separator", "--env_info"],
                   capture_output=True, text=True, check=True)
      out = (res.stdout or "") + (res.stderr or "")
      return "CoreMLExecutionProvider" in out


  def build_separator(output_dir, model_dir):
      from audio_separator.separator import Separator
      sep = Separator(output_dir=str(output_dir), model_file_dir=str(model_dir),
                      output_format="WAV")
      sep.load_model(model_filename=ROFORMER_MODEL)
      return sep


  def pick_vocal_stem(output_files: list[str]) -> str:
      for f in output_files:
          name = Path(f).name
          if "(Vocals)" in name or "_Vocals" in name or "vocals" in name.lower():
              return f
      raise ValueError(f"no vocal stem in {output_files}")


  def separate_vocals(separator, in_wav) -> str:
      return pick_vocal_stem(separator.separate(str(in_wav)))
  ```

- [ ] **Step 4: Run & show expected PASS.** `cd ~/jarvis && python -m pytest tests/voice_training/test_separate.py -q` → **4 passed**.

- [ ] **Step 5: Commit.** `cd ~/jarvis && git add -A && git commit -m "M2: voice_training separate (BS-Roformer CoreML, env_info gate)"`

---

### Task 3: `voice_training/segment.py` — silence split into 3–12 s clips (+ install soundfile)

**Files:**
- Create: `~/jarvis/voice_training/segment.py`
- Test: `~/jarvis/tests/voice_training/test_segment.py`

- [ ] **Step 1: Install the `[voice]` extra (main venv) — pinned, reproducible.** The `voice` optional-dependency group (`soundfile==0.13.1`, `noisereduce==3.0.3`, `faiss-cpu>=1.7.2`, `mlx-rvc`, `audio-separator==0.44.2`) is already declared in `pyproject.toml` (M1 T1). Install it in one shot instead of imperative one-off `pip install`s:
  ```bash
  brew install swig                                   # build prereq for faiss-cpu
  cd ~/jarvis && ./.venv/bin/pip install -e ".[voice]"
  ```
  Expected (tail): `Successfully installed ... soundfile-0.13.1 noisereduce-3.0.3 faiss-cpu-... mlx-rvc-... audio-separator-0.44.2`. This single install covers `soundfile` (used here + RVC), `noisereduce` (Task 4), and `faiss-cpu`/`mlx-rvc` (Task 11) — later tasks NO LONGER run their own `pip install`. (For the actual dataset run you also need the `training` extra — `pip install -e ".[training]"` for `yt-dlp`/`demucs`; see the README.)

- [ ] **Step 2: Write the failing test.** Create `~/jarvis/tests/voice_training/test_segment.py`:
  ```python
  import numpy as np
  from voice_training import segment


  def _tone(dur_s, sr=16000, f=220.0):
      t = np.arange(int(dur_s * sr)) / sr
      return (0.5 * np.sin(2 * np.pi * f * t)).astype(np.float32)


  def test_find_segments_splits_on_silence():
      sr = 16000
      sig = np.concatenate([_tone(4, sr), np.zeros(int(0.5 * sr), np.float32), _tone(5, sr)])
      segs = segment.find_segments(sig, sr, min_s=3.0, max_s=12.0)
      assert len(segs) == 2
      for s, e in segs:
          assert 3.0 <= (e - s) / sr <= 12.0


  def test_find_segments_hard_splits_long_run():
      sr = 16000
      segs = segment.find_segments(_tone(20, sr), sr, min_s=3.0, max_s=12.0)
      assert all((e - s) / sr <= 12.0 for s, e in segs)
      assert sum(e - s for s, e in segs) > 12 * sr


  def test_export_segments_writes_wavs(tmp_path):
      import soundfile as sf
      sr = 16000
      sig = _tone(4, sr)
      paths = segment.export_segments(sig, sr, [(0, len(sig))], tmp_path)
      data, rate = sf.read(paths[0], dtype="float32")
      assert len(paths) == 1 and rate == sr and len(data) == len(sig)
  ```

- [ ] **Step 3: Run & show expected FAIL.** `cd ~/jarvis && python -m pytest tests/voice_training/test_segment.py -q` → **FAILS** `ModuleNotFoundError: voice_training.segment`.

- [ ] **Step 4: Minimal implementation.** Create `~/jarvis/voice_training/segment.py`:
  ```python
  """Split a long vocal track into 3-12s utterance clips by silence.

  Energy-gated, pure-numpy so it is unit-testable without ffmpeg. 20ms frames
  below silence_thresh_db are silence; a silent run >= min_silence_s cuts the
  voiced span. Voiced spans shorter than min_s are dropped; spans longer than
  max_s are hard-split at max_s.
  """
  from __future__ import annotations
  from pathlib import Path
  import numpy as np


  def _frame_rms_db(pcm: np.ndarray, frame: int) -> np.ndarray:
      n = len(pcm) // frame
      if n == 0:
          return np.array([], dtype=np.float64)
      blk = pcm[: n * frame].reshape(n, frame).astype(np.float64)
      rms = np.sqrt(np.mean(blk ** 2, axis=1) + 1e-12)
      return 20.0 * np.log10(rms + 1e-12)


  def find_segments(pcm, sr, min_s=3.0, max_s=12.0,
                    silence_thresh_db=-40.0, min_silence_s=0.3):
      pcm = np.asarray(pcm, dtype=np.float32).reshape(-1)
      frame = max(1, int(sr * 0.02))
      voiced = _frame_rms_db(pcm, frame) > silence_thresh_db
      min_sil = max(1, int(round(min_silence_s / 0.02)))
      min_len, max_len = int(min_s * sr), int(max_s * sr)
      segs, i, nf = [], 0, len(voiced)
      while i < nf:
          if not voiced[i]:
              i += 1
              continue
          j, sil = i, 0
          while j < nf:
              if voiced[j]:
                  sil, j = 0, j + 1
              else:
                  sil += 1
                  if sil >= min_sil:
                      break
                  j += 1
          end_frame = j - sil if sil else j
          start, end = i * frame, min(len(pcm), end_frame * frame)
          span = start
          while end - span > max_len:
              segs.append((span, span + max_len))
              span += max_len
          if end - span >= min_len:
              segs.append((span, end))
          i = j + 1
      return segs


  def export_segments(pcm, sr, segs, out_dir, prefix="seg") -> list[str]:
      import soundfile as sf
      out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
      paths = []
      for k, (s, e) in enumerate(segs):
          p = out / f"{prefix}_{k:04d}.wav"
          sf.write(str(p), np.asarray(pcm[s:e], dtype=np.float32), sr)
          paths.append(str(p))
      return paths
  ```

- [ ] **Step 5: Run & show expected PASS.** `cd ~/jarvis && python -m pytest tests/voice_training/test_segment.py -q` → **3 passed**.

- [ ] **Step 6: Commit.** `cd ~/jarvis && git add -A && git commit -m "M2: voice_training segment (energy silence split 3-12s) + soundfile"`

---

### Task 4: `voice_training/clean.py` — noisereduce denoise

**Files:**
- Create: `~/jarvis/voice_training/clean.py`
- Test: `~/jarvis/tests/voice_training/test_clean.py`

- [ ] **Step 1: Write the failing test.** (`noisereduce==3.0.3` was already installed via the `[voice]` extra in Task 3 — no separate install here.) Create `~/jarvis/tests/voice_training/test_clean.py`:
  ```python
  import numpy as np
  from voice_training import clean


  def test_denoise_keeps_shape_and_reduces_energy():
      sr = 16000
      rng = np.random.default_rng(0)
      t = np.arange(2 * sr) / sr
      tone = 0.3 * np.sin(2 * np.pi * 200 * t).astype(np.float32)
      noisy = (tone + 0.05 * rng.standard_normal(t.size)).astype(np.float32)
      out = clean.denoise(noisy, sr, stationary=True)
      assert out.shape == noisy.shape and out.dtype == np.float32
      rms = lambda x: float(np.sqrt(np.mean(x ** 2)))
      assert rms(out) <= rms(noisy) + 1e-6
  ```

- [ ] **Step 2: Run & show expected FAIL.** `cd ~/jarvis && python -m pytest tests/voice_training/test_clean.py -q` → **FAILS** `ModuleNotFoundError: voice_training.clean`.

- [ ] **Step 3: Minimal implementation.** Create `~/jarvis/voice_training/clean.py`:
  ```python
  """Denoise vocal clips with noisereduce (spectral gating, default path).

  resemble-enhance is optional/fragile (Colab only); noisereduce is the default
  on-device cleaner. prop_decrease=0.9 keeps speech intact while suppressing hiss.
  """
  from __future__ import annotations
  import numpy as np


  def denoise(pcm, sr, prop_decrease: float = 0.9, stationary: bool = False) -> np.ndarray:
      import noisereduce as nr
      x = np.asarray(pcm, dtype=np.float32).reshape(-1)
      out = nr.reduce_noise(y=x, sr=sr, prop_decrease=prop_decrease, stationary=stationary)
      return np.asarray(out, dtype=np.float32)
  ```

- [ ] **Step 4: Run & show expected PASS.** `cd ~/jarvis && python -m pytest tests/voice_training/test_clean.py -q` → **1 passed**.

- [ ] **Step 5: Commit.** `cd ~/jarvis && git add -A && git commit -m "M2: voice_training clean (noisereduce default)"`

---

### Task 5: `voice_training/resample.py` — ffmpeg → 40 kHz mono s16

**Files:**
- Create: `~/jarvis/voice_training/resample.py`
- Test: `~/jarvis/tests/voice_training/test_resample.py`

- [ ] **Step 1: Write the failing test.** Create `~/jarvis/tests/voice_training/test_resample.py`:
  ```python
  from voice_training import resample


  def test_build_ffmpeg_resample_cmd_exact():
      cmd = resample.build_ffmpeg_resample_cmd("a.wav", "b.wav", 40000)
      assert cmd == ["ffmpeg", "-y", "-i", "a.wav", "-ar", "40000", "-ac", "1",
                     "-sample_fmt", "s16", "b.wav"]


  def test_resample_file_invokes_runner(tmp_path):
      seen = {}
      def fake(cmd, check):
          seen["cmd"] = cmd
      out = resample.resample_file(tmp_path / "in.wav", tmp_path / "out.wav", runner=fake)
      assert out.endswith("out.wav")
      assert seen["cmd"][0] == "ffmpeg" and "40000" in seen["cmd"]
  ```

- [ ] **Step 2: Run & show expected FAIL.** `cd ~/jarvis && python -m pytest tests/voice_training/test_resample.py -q` → **FAILS** `ModuleNotFoundError: voice_training.resample`.

- [ ] **Step 3: Minimal implementation.** Create `~/jarvis/voice_training/resample.py`:
  ```python
  """Resample cleaned clips to RVC training format: 40000 Hz mono s16 WAV (ffmpeg)."""
  from __future__ import annotations
  import subprocess
  from pathlib import Path


  def build_ffmpeg_resample_cmd(in_wav, out_wav, rate: int = 40000) -> list[str]:
      return ["ffmpeg", "-y", "-i", str(in_wav),
              "-ar", str(rate), "-ac", "1", "-sample_fmt", "s16", str(out_wav)]


  def resample_file(in_wav, out_wav, rate: int = 40000, runner=subprocess.run) -> str:
      Path(out_wav).parent.mkdir(parents=True, exist_ok=True)
      runner(build_ffmpeg_resample_cmd(in_wav, out_wav, rate), check=True)
      return str(out_wav)
  ```

- [ ] **Step 4: Run & show expected PASS.** `cd ~/jarvis && python -m pytest tests/voice_training/test_resample.py -q` → **2 passed**.

- [ ] **Step 5: Commit.** `cd ~/jarvis && git add -A && git commit -m "M2: voice_training resample (ffmpeg 40kHz mono s16)"`

---

### Task 6: `build_dataset.py` local pipeline + `train_colab.ipynb` + `README.md`

**Files:**
- Create: `~/jarvis/voice_training/build_dataset.py`
- Create: `~/jarvis/voice_training/make_train_colab_nb.py` (nbformat generator script)
- Create: `~/jarvis/voice_training/train_colab.ipynb` (REAL `.ipynb` emitted by the generator — Colab/CUDA only)
- Create: `~/jarvis/voice_training/README.md`
- Test: `~/jarvis/tests/voice_training/test_build_dataset.py`

- [ ] **Step 1: Write the failing test (pipeline ordering).** Create `~/jarvis/tests/voice_training/test_build_dataset.py`:
  ```python
  import numpy as np
  import soundfile as sf
  from voice_training import build_dataset


  def test_build_one_runs_pipeline_in_order(tmp_path, monkeypatch):
      order = []
      bd = build_dataset
      monkeypatch.setattr(bd.separate, "separate_vocals",
                          lambda sep, w: order.append("separate") or str(tmp_path / "voc.wav"))
      monkeypatch.setattr(bd.segment, "find_segments",
                          lambda pcm, sr, **k: order.append("segment") or [(0, len(pcm))])
      monkeypatch.setattr(bd.segment, "export_segments",
                          lambda pcm, sr, segs, d, **k: [str(tmp_path / "c0.wav")])
      monkeypatch.setattr(bd.clean, "denoise",
                          lambda pcm, sr, **k: order.append("clean") or pcm)
      monkeypatch.setattr(bd.resample, "resample_file",
                          lambda i, o, **k: order.append("resample") or str(o))
      sr = 16000
      sf.write(tmp_path / "voc.wav", np.zeros(sr, np.float32), sr)
      sf.write(tmp_path / "c0.wav", np.zeros(sr, np.float32), sr)
      out = build_dataset.build_one(str(tmp_path / "raw.wav"), tmp_path, tmp_path, separator=object())
      assert order == ["separate", "segment", "clean", "resample"]
      assert out and out[0].endswith("_40k.wav")
  ```

- [ ] **Step 2: Run & show expected FAIL.** `cd ~/jarvis && python -m pytest tests/voice_training/test_build_dataset.py -q` → **FAILS** `ModuleNotFoundError: voice_training.build_dataset`.

- [ ] **Step 3: Minimal implementation.** Create `~/jarvis/voice_training/build_dataset.py`:
  ```python
  """Local dataset build: raw vocals WAVs -> isolated -> 3-12s clips -> denoise
  -> 40kHz mono s16. RVC TRAINING itself is CUDA/Colab only (see README +
  train_colab.ipynb); this only prepares the dataset locally.

  Usage:
      python -m voice_training.build_dataset --raw RAW --work WORK --out OUT
  """
  from __future__ import annotations
  import argparse
  from pathlib import Path
  import numpy as np

  from voice_training import separate, segment, clean, resample


  def build_one(in_wav: str, work_dir: Path, out_dir: Path, separator) -> list[str]:
      import soundfile as sf
      work_dir, out_dir = Path(work_dir), Path(out_dir)
      vocals = separate.separate_vocals(separator, in_wav)
      pcm, sr = sf.read(vocals, dtype="float32")
      if pcm.ndim > 1:
          pcm = pcm.mean(axis=1).astype(np.float32)
      segs = segment.find_segments(pcm, sr)
      clip_paths = segment.export_segments(pcm, sr, segs, work_dir / Path(in_wav).stem)
      finals: list[str] = []
      for clip in clip_paths:
          cp, csr = sf.read(clip, dtype="float32")
          sf.write(clip, clean.denoise(cp, csr), csr)
          out_wav = out_dir / (Path(clip).stem + "_40k.wav")
          resample.resample_file(clip, out_wav)
          finals.append(str(out_wav))
      return finals


  def main(argv=None) -> list[str]:
      ap = argparse.ArgumentParser()
      ap.add_argument("--raw", required=True)
      ap.add_argument("--work", required=True)
      ap.add_argument("--out", required=True)
      ap.add_argument("--model-dir",
                      default=str(Path.home() / ".cache" / "audio-separator-models"))
      a = ap.parse_args(argv)
      work, out = Path(a.work), Path(a.out)
      work.mkdir(parents=True, exist_ok=True)
      out.mkdir(parents=True, exist_ok=True)
      if not separate.check_env():
          raise RuntimeError("CoreMLExecutionProvider missing; run: audio-separator --env_info")
      sep = separate.build_separator(work, a.model_dir)
      finals: list[str] = []
      for raw in sorted(Path(a.raw).glob("*.wav")):
          finals.extend(build_one(str(raw), work, out, sep))
      print(f"built {len(finals)} clips -> {out}")
      return finals


  if __name__ == "__main__":
      main()
  ```

- [ ] **Step 4: Run & show expected PASS.** `cd ~/jarvis && python -m pytest tests/voice_training/test_build_dataset.py -q` → **1 passed**.

- [ ] **Step 5: Emit `train_colab.ipynb` as a REAL `.ipynb` via a committed `nbformat` generator (NO prose-only notebook).** RVC v2 training is CUDA/Colab-only (MPS training quality is poor), so the notebook is authored by a committed script that writes a genuine `nbformat` v4 file with concrete cells, then both the script and the `.ipynb` are committed. Install the one-off authoring tool:
  ```bash
  ~/jarvis/.venv/bin/pip install nbformat
  ```
  Create `~/jarvis/voice_training/make_train_colab_nb.py`:
  ```python
  """Generate voice_training/train_colab.ipynb (RVC v2 training, Colab/CUDA only).

  Run once from the main venv to (re)emit the notebook; commit BOTH this script
  and the generated train_colab.ipynb:
      ~/jarvis/.venv/bin/python voice_training/make_train_colab_nb.py
  """
  from __future__ import annotations
  from pathlib import Path
  import nbformat as nbf

  INTRO = (
      "# JARVIS RVC v2 training (Colab GPU only)\n\n"
      "Upload `dataset/` (40 kHz mono s16 WAV, **10-30 min CLEAN single-speaker vocals**,\n"
      "no music/reverb). Runtime -> Change runtime type -> **GPU (T4/A100)**.\n"
      "Mac MPS training is low-quality — do NOT train locally. Target ~150-300 epochs, batch ~40."
  )
  CLONE = (
      "!git clone https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI.git rvc\n"
      "%cd rvc\n"
      "!pip install -r requirements.txt\n"
      "!python tools/download_models.py"
  )
  PREPROCESS = (
      "# preprocess: sr=40000, n_cpu=4, exp=jarvis (dataset at /content/dataset)\n"
      "!python infer/modules/train/preprocess.py /content/dataset 40000 4 ./logs/jarvis True 3.0"
  )
  EXTRACT = (
      "# F0 (RMVPE) + HuBERT feature extraction (v2)\n"
      "!python infer/modules/train/extract/extract_f0_rmvpe.py 1 0 0 ./logs/jarvis True\n"
      "!python infer/modules/train/extract_feature_print.py cuda:0 1 0 ./logs/jarvis v2"
  )
  TRAIN = (
      "# train: ~150-300 epochs (-te), batch 40 (-bs), save every 25 (-se)\n"
      "!python infer/modules/train/train.py -e jarvis -sr 40k -f0 1 -bs 40 -te 250 -se 25 \\\n"
      "  -pg assets/pretrained_v2/f0G40k.pth -pd assets/pretrained_v2/f0D40k.pth -l 0 -c 0 -sw 1 -v v2"
  )
  INDEX = (
      "# build the faiss index, then download the two artifacts\n"
      "!python tools/train_index.py jarvis v2\n"
      "from google.colab import files\n"
      "files.download('logs/jarvis/added_IVF_jarvis_v2.index')\n"
      "files.download('assets/weights/jarvis.pth')"
  )
  OUTRO = (
      "## Install the result on the Mac\n\n"
      "Copy BOTH `jarvis.pth` + `added_IVF_jarvis_v2.index` into `~/jarvis/voice_models/`\n"
      "(so `rvc_model_path` / `rvc_index_path` resolve), then run JARVIS with\n"
      "`JARVIS_TTS_BACKEND=melotts JARVIS_VC_BACKEND=rvc python -m jarvis`."
  )


  def build_notebook() -> nbf.NotebookNode:
      nb = nbf.v4.new_notebook()
      nb.cells = [
          nbf.v4.new_markdown_cell(INTRO),
          nbf.v4.new_code_cell(CLONE),
          nbf.v4.new_code_cell(PREPROCESS),
          nbf.v4.new_code_cell(EXTRACT),
          nbf.v4.new_code_cell(TRAIN),
          nbf.v4.new_code_cell(INDEX),
          nbf.v4.new_markdown_cell(OUTRO),
      ]
      nb.metadata["accelerator"] = "GPU"
      nb.metadata["colab"] = {"provenance": []}
      nb.metadata["kernelspec"] = {"name": "python3", "display_name": "Python 3"}
      return nb


  def main() -> str:
      out = Path(__file__).resolve().parent / "train_colab.ipynb"
      nb = build_notebook()
      nbf.write(nb, str(out))
      print(f"wrote {out} ({len(nb.cells)} cells)")
      return str(out)


  if __name__ == "__main__":
      main()
  ```
  Generate the committed notebook:
  ```bash
  cd ~/jarvis && ./.venv/bin/python voice_training/make_train_colab_nb.py
  ```
  Expected: `wrote .../voice_training/train_colab.ipynb (7 cells)`.

  **Manual verification:** `cd ~/jarvis && ./.venv/bin/python -c "import nbformat; nb=nbformat.read('voice_training/train_colab.ipynb', as_version=4); print(len(nb.cells), [c.cell_type for c in nb.cells])"` → prints `7 ['markdown', 'code', 'code', 'code', 'code', 'code', 'markdown']`. Opening in Colab and running through Cell 6 offers `jarvis.pth` + `added_IVF_jarvis_v2.index` for download.

- [ ] **Step 6: Author `README.md`.** Create `~/jarvis/voice_training/README.md`:
  ```markdown
  # JARVIS voice training pipeline

  Personal/local voice cloning ONLY — no redistribution of audio or the model.

  ## Run order (local, main .venv)
  0. Install extras (pinned, reproducible): `pip install -e ".[voice,training]"`
     (voice = soundfile/noisereduce/faiss-cpu/mlx-rvc/audio-separator; training = yt-dlp/demucs).
  1. Edit `urls.txt` (copy of `urls.example.txt`). Print the list for approval:
     `python -c "from voice_training import fetch; print(fetch.print_share_list(fetch.load_urls('voice_training/urls.txt')))"`
  2. After approval: `python -c "from voice_training import fetch; \
     u=fetch.load_urls('voice_training/urls.txt'); \
     fetch.fetch_all(u, '~/jarvis/voice_data/raw', confirmed=True)"`
  3. `audio-separator --env_info`  → confirm `CoreMLExecutionProvider`.
  4. `python -m voice_training.build_dataset --raw ~/jarvis/voice_data/raw \
       --work ~/jarvis/voice_data/work --out ~/jarvis/voice_data/dataset`
     (separate → 3–12s split → noisereduce → 40 kHz mono s16).
  5. Auto-delete raws: `python -c "from voice_training import fetch; \
     fetch.delete_raws('~/jarvis/voice_data/raw')"`.
  6. Upload `dataset/` to Colab; run `train_colab.ipynb` (CUDA only).
  7. Copy `jarvis.pth` + `added_*.index` to `~/jarvis/voice_models/`.

  ## Dataset targets
  - RVC v2: **10–30 minutes** of CLEAN single-speaker vocals (no music/reverb).
  - Clips 3–12 s each, 40 000 Hz mono s16.
  - Training: ~150–300 epochs, batch ~40. Mac MPS training is low-quality — use Colab GPU.

  ## Fallbacks
  - Separation: demucs-mlx (`uv pip install demucs-mlx`) if BS-Roformer/CoreML fails.
  - Denoise: resemble-enhance is optional/fragile (Colab); noisereduce is the default.
  ```

- [ ] **Step 7: Commit.** `cd ~/jarvis && git add -A && git commit -m "M2: voice_training build_dataset pipeline + nbformat-generated Colab notebook + README"`

---

### Task 7: `jarvis/tts/ipc.py` — main↔worker framing (JSON header + float32 PCM)

**Files:**
- Create: `~/jarvis/jarvis/tts/ipc.py`
- Test: `~/jarvis/tests/tts/test_ipc.py`

- [ ] **Step 1: Write the failing test.** Create `~/jarvis/tests/tts/test_ipc.py`:
  ```python
  import io
  import numpy as np
  import pytest
  from jarvis.tts import ipc


  def test_request_roundtrip():
      assert ipc.read_request(io.BytesIO(ipc.pack_request("안녕하세요"))) == "안녕하세요"


  def test_request_eof_returns_none():
      assert ipc.read_request(io.BytesIO(b"")) is None


  def test_response_roundtrip_pcm():
      pcm = np.linspace(-1, 1, 2048, dtype=np.float32)
      out, sr = ipc.read_response(io.BytesIO(ipc.pack_response(pcm, 44100)))
      assert sr == 44100 and out.dtype == np.float32 and out.shape == pcm.shape
      np.testing.assert_allclose(out, pcm, atol=1e-6)


  def test_error_response_raises():
      with pytest.raises(RuntimeError, match="boom"):
          ipc.read_response(io.BytesIO(ipc.pack_error("boom")))
  ```

- [ ] **Step 2: Run & show expected FAIL.** `cd ~/jarvis && python -m pytest tests/tts/test_ipc.py -q` → **FAILS** `ModuleNotFoundError: jarvis.tts.ipc`.

- [ ] **Step 3: Minimal implementation.** Create `~/jarvis/jarvis/tts/ipc.py`:
  ```python
  """Framed IPC between the main venv and the MeloTTS worker (.venv-tts).

  Per message: one JSON header line ('\\n'-terminated) + optional raw payload.
    Request : {"type":"synth","text":"..."}                         (no payload)
    Response: {"type":"pcm","sample_rate":44100,"nbytes":N}\\n<N bytes float32 LE>
            | {"type":"error","message":"..."}                      (no payload)
  PCM is mono float32 little-endian in [-1, 1] at sample_rate.
  """
  from __future__ import annotations
  import json
  import numpy as np


  def pack_request(text: str) -> bytes:
      return json.dumps({"type": "synth", "text": text}, ensure_ascii=False).encode("utf-8") + b"\n"


  def read_request(stream):
      line = stream.readline()
      if not line:
          return None
      msg = json.loads(line.decode("utf-8"))
      if msg.get("type") != "synth":
          raise ValueError(f"unexpected request: {msg!r}")
      return msg["text"]


  def pack_response(pcm, sample_rate: int) -> bytes:
      buf = np.asarray(pcm, dtype="<f4").tobytes()
      header = json.dumps({"type": "pcm", "sample_rate": int(sample_rate),
                           "nbytes": len(buf)}).encode("utf-8") + b"\n"
      return header + buf


  def pack_error(message: str) -> bytes:
      return json.dumps({"type": "error", "message": message}).encode("utf-8") + b"\n"


  def _read_exact(stream, n: int) -> bytes:
      chunks, got = [], 0
      while got < n:
          c = stream.read(n - got)
          if not c:
              raise EOFError("short read from tts worker")
          chunks.append(c); got += len(c)
      return b"".join(chunks)


  def read_response(stream):
      line = stream.readline()
      if not line:
          raise EOFError("tts worker closed the stream")
      msg = json.loads(line.decode("utf-8"))
      if msg.get("type") == "error":
          raise RuntimeError(f"tts worker error: {msg.get('message')}")
      if msg.get("type") != "pcm":
          raise ValueError(f"unexpected response: {msg!r}")
      raw = _read_exact(stream, int(msg["nbytes"]))
      return np.frombuffer(raw, dtype="<f4").astype(np.float32), int(msg["sample_rate"])
  ```

- [ ] **Step 4: Run & show expected PASS.** `cd ~/jarvis && python -m pytest tests/tts/test_ipc.py -q` → **4 passed**.

- [ ] **Step 5: Commit.** `cd ~/jarvis && git add -A && git commit -m "M2: tts IPC framing (JSON header + float32 PCM)"`

---

### Task 8: `jarvis/tts/tts_worker.py` — persistent MeloTTS-KR worker loop

**Files:**
- Create: `~/jarvis/jarvis/tts/tts_worker.py`
- Test: `~/jarvis/tests/tts/test_tts_worker.py`

- [ ] **Step 1: Write the failing test (hermetic, sine synth — no MeloTTS).** Create `~/jarvis/tests/tts/test_tts_worker.py`:
  ```python
  import io
  import numpy as np
  import pytest
  from jarvis.tts import ipc, tts_worker


  def _sine_synth(text):
      sr = 44100
      t = np.arange(int(0.1 * sr)) / sr
      return (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), sr


  def test_run_once_synthesizes_and_frames_response():
      out = io.BytesIO()
      assert tts_worker.run_once(_sine_synth, io.BytesIO(ipc.pack_request("테스트")), out) is True
      out.seek(0)
      pcm, sr = ipc.read_response(out)
      assert sr == 44100 and pcm.shape[0] == int(0.1 * 44100)


  def test_run_once_eof_returns_false():
      assert tts_worker.run_once(_sine_synth, io.BytesIO(b""), io.BytesIO()) is False


  def test_run_once_reports_synth_error():
      def boom(text):
          raise ValueError("nope")
      out = io.BytesIO()
      tts_worker.run_once(boom, io.BytesIO(ipc.pack_request("x")), out)
      out.seek(0)
      with pytest.raises(RuntimeError, match="nope"):
          ipc.read_response(out)
  ```

- [ ] **Step 2: Run & show expected FAIL.** `cd ~/jarvis && python -m pytest tests/tts/test_tts_worker.py -q` → **FAILS** `ModuleNotFoundError: jarvis.tts.tts_worker`.

- [ ] **Step 3: Minimal implementation.** Create `~/jarvis/jarvis/tts/tts_worker.py`:
  ```python
  """Persistent MeloTTS-KR worker. Runs INSIDE .venv-tts ONLY (never called by
  the main venv — make_melo_synth() imports melo lazily). Reads synth requests
  on stdin, writes float32 PCM on stdout via jarvis.tts.ipc. MeloTTS -> 44100 Hz.

  Run:  ~/jarvis/.venv-tts/bin/python -m jarvis.tts.tts_worker
  """
  from __future__ import annotations
  import sys
  import numpy as np

  from jarvis.tts import ipc

  SAMPLE_RATE = 44100


  def make_melo_synth():
      """Build the real MeloTTS-KR synth: text -> (float32 pcm, 44100)."""
      import os, tempfile
      import soundfile as sf
      from melo.api import TTS
      model = TTS(language="KR", device="cpu")
      spk = model.hps.data.spk2id["KR"]

      def synth(text: str):
          fd, path = tempfile.mkstemp(suffix=".wav")
          os.close(fd)
          try:
              model.tts_to_file(text, spk, path, speed=1.0)
              pcm, sr = sf.read(path, dtype="float32")
              if pcm.ndim > 1:
                  pcm = pcm.mean(axis=1).astype(np.float32)
              return pcm.astype(np.float32), sr
          finally:
              os.unlink(path)
      return synth


  def run_once(synth, in_stream, out_stream) -> bool:
      text = ipc.read_request(in_stream)
      if text is None:
          return False
      try:
          pcm, sr = synth(text)
          out_stream.write(ipc.pack_response(pcm, sr))
      except Exception as exc:  # report, keep serving
          out_stream.write(ipc.pack_error(repr(exc)))
      out_stream.flush()
      return True


  def serve(synth, in_stream, out_stream) -> None:
      while run_once(synth, in_stream, out_stream):
          pass


  def main() -> None:
      serve(make_melo_synth(), sys.stdin.buffer, sys.stdout.buffer)


  if __name__ == "__main__":
      main()
  ```

- [ ] **Step 4: Run & show expected PASS.** `cd ~/jarvis && python -m pytest tests/tts/test_tts_worker.py -q` → **3 passed**.

- [ ] **Step 5: Commit.** `cd ~/jarvis && git add -A && git commit -m "M2: tts_worker loop (lazy MeloTTS synth, error framing)"`

---

### Task 9: `jarvis/tts/melotts_kr.py` — `MeloTTSKR(TTSBackend)` over the worker subprocess

**Files:**
- Create: `~/jarvis/jarvis/tts/melotts_kr.py`
- Create: `~/jarvis/tests/tts/fake_worker.py` (hermetic stand-in worker)
- Test: `~/jarvis/tests/tts/test_melotts_kr.py`

- [ ] **Step 1: Write the failing test (real subprocess, fake worker).** Create `~/jarvis/tests/tts/fake_worker.py`:
  ```python
  """Hermetic stand-in for the MeloTTS worker: 0.1s 440Hz sine for any text,
  using the real ipc framing. No MeloTTS / no .venv-tts required."""
  import sys
  import numpy as np
  from jarvis.tts import ipc, tts_worker


  def _sine(text):
      sr = 44100
      t = np.arange(int(0.1 * sr)) / sr
      return (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32), sr


  if __name__ == "__main__":
      tts_worker.serve(_sine, sys.stdin.buffer, sys.stdout.buffer)
  ```
  Create `~/jarvis/tests/tts/test_melotts_kr.py`:
  ```python
  import asyncio
  import sys
  from pathlib import Path
  import numpy as np
  from jarvis.tts.melotts_kr import MeloTTSKR

  FAKE = str(Path(__file__).parent / "fake_worker.py")


  def test_warm_and_synth_over_subprocess():
      tts = MeloTTSKR(worker_cmd=[sys.executable, FAKE])
      tts.warm()
      try:
          pcm = asyncio.run(tts.synth("안녕"))
          assert isinstance(pcm, np.ndarray) and pcm.dtype == np.float32
          assert pcm.shape[0] == int(0.1 * 44100)
          pcm2 = asyncio.run(tts.synth("또"))   # reuses the same persistent worker
          assert pcm2.shape == pcm.shape
      finally:
          tts.close()


  def test_sample_rate_is_44100():
      assert MeloTTSKR.sample_rate == 44100
  ```

- [ ] **Step 2: Run & show expected FAIL.** `cd ~/jarvis && python -m pytest tests/tts/test_melotts_kr.py -q` → **FAILS** `ModuleNotFoundError: jarvis.tts.melotts_kr`.

- [ ] **Step 3: Minimal implementation.** Create `~/jarvis/jarvis/tts/melotts_kr.py`:
  ```python
  """MeloTTS-KR backend (TTSBackend). Spawns the .venv-tts worker
  (jarvis.tts.tts_worker) as a persistent subprocess and exchanges float32 PCM
  over jarvis.tts.ipc. 44100 Hz mono.

  TWO-VENV ISOLATION: .venv-tts does NOT pip-install the main package. The worker
  reaches jarvis.tts.ipc + jarvis.tts.tts_worker (import-light: stdlib + numpy;
  MeloTTS imported lazily inside the worker) ONLY because we launch the subprocess
  with PYTHONPATH=<repo root> (default /Users/2seongjae/jarvis)."""
  from __future__ import annotations
  import asyncio
  import os
  import subprocess
  import sys
  import numpy as np

  from jarvis.tts import ipc


  class MeloTTSKR:
      sample_rate: int = 44100

      def __init__(self, worker_cmd: list[str] | None = None, sample_rate: int = 44100,
                   repo_root: str | None = None):
          self.sample_rate = sample_rate
          self._cmd = worker_cmd or [
              os.path.expanduser("~/jarvis/.venv-tts/bin/python"),
              "-m", "jarvis.tts.tts_worker",
          ]
          # TWO-VENV ISOLATION: .venv-tts has no editable install of the main package,
          # so the worker can only import jarvis.tts.* via PYTHONPATH=<repo root>.
          self._repo_root = os.path.expanduser(repo_root or "~/jarvis")
          self._env = {**os.environ, "PYTHONPATH": self._repo_root}
          self._proc: subprocess.Popen | None = None
          self._lock = asyncio.Lock()

      def _ensure_proc(self) -> subprocess.Popen:
          if self._proc is None or self._proc.poll() is not None:
              self._proc = subprocess.Popen(
                  self._cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                  stderr=sys.stderr, bufsize=0, env=self._env)
          return self._proc

      def warm(self) -> None:
          proc = self._ensure_proc()
          proc.stdin.write(ipc.pack_request("준비 완료"))
          proc.stdin.flush()
          _pcm, sr = ipc.read_response(proc.stdout)  # discard warm-up audio
          self.sample_rate = sr

      async def synth(self, text: str) -> np.ndarray:
          async with self._lock:
              pcm, _sr = await asyncio.to_thread(self._synth_blocking, text)
              return pcm

      def _synth_blocking(self, text: str):
          proc = self._ensure_proc()
          proc.stdin.write(ipc.pack_request(text))
          proc.stdin.flush()
          return ipc.read_response(proc.stdout)

      def close(self) -> None:
          if self._proc and self._proc.poll() is None:
              try:
                  self._proc.stdin.close()
                  self._proc.wait(timeout=5)
              except Exception:
                  self._proc.kill()
          self._proc = None
  ```

- [ ] **Step 4: Run & show expected PASS.** `cd ~/jarvis && python -m pytest tests/tts/test_melotts_kr.py -q` → **2 passed**.

- [ ] **Step 5: Commit.** `cd ~/jarvis && git add -A && git commit -m "M2: MeloTTSKR backend over persistent .venv-tts worker"`

---

### Task 10: Install MeloTTS in `.venv-tts` + MeCab recipe + Korean smoke test (manual verification)

**Files:**
- Create: `~/jarvis/scripts/tts_smoke.py`

- [ ] **Step 1: Create the `.venv-tts` and install MeloTTS + Korean MeCab.** Run exactly (do NOT install `mecab-python3` or `brew install mecab` — `python-mecab-ko` bundles `mecab-ko-dic`; and do **NOT** `pip install -e ~/jarvis` into `.venv-tts` — two-venv isolation, the worker reaches `jarvis.tts.*` via `PYTHONPATH`, which `MeloTTSKR` sets automatically):
  ```bash
  python3.11 -m venv ~/jarvis/.venv-tts
  ~/jarvis/.venv-tts/bin/pip install -U pip wheel
  ~/jarvis/.venv-tts/bin/pip install python-mecab-ko          # Korean MeCab (bundled dic)
  ~/jarvis/.venv-tts/bin/pip install git+https://github.com/myshell-ai/MeloTTS.git
  ~/jarvis/.venv-tts/bin/pip install soundfile==0.13.1        # worker reads MeloTTS WAV
  ```
  TWO-VENV ISOLATION: the only `jarvis` code the worker imports is `jarvis.tts.ipc` + `jarvis.tts.tts_worker`, both import-light (stdlib + numpy; MeloTTS imported lazily inside the worker). The main↔worker bridge `MeloTTSKR` launches the worker with `PYTHONPATH=/Users/2seongjae/jarvis`, so these resolve WITHOUT installing the package into `.venv-tts`. Verify import-lightness from the MAIN venv (which has NO MeloTTS): `~/jarvis/.venv/bin/python -c "import jarvis.tts.ipc, jarvis.tts.tts_worker; print('worker import OK — stdlib+numpy only')"` succeeds (it would raise `ModuleNotFoundError: melo` if MeloTTS were imported at module top).
  Notes: let MeloTTS pull its own pinned torch/transformers; only override if import fails. Korean does NOT need `python -m unidic download` (that is Japanese) — if `melo.api` import raises a unidic error, run `~/jarvis/.venv-tts/bin/python -m unidic download` once.

- [ ] **Step 2: Author the smoke script.** Create `~/jarvis/scripts/tts_smoke.py`:
  ```python
  """MeloTTS-KR smoke test. Run with: ~/jarvis/.venv-tts/bin/python scripts/tts_smoke.py"""
  import time
  import soundfile as sf
  from melo.api import TTS

  m = TTS(language="KR", device="cpu")
  spk = m.hps.data.spk2id["KR"]
  t0 = time.time()
  m.tts_to_file("안녕하세요. 저는 자비스입니다. 무엇을 도와드릴까요?", spk,
                "/tmp/jarvis_tts_smoke.wav", speed=1.0)
  data, sr = sf.read("/tmp/jarvis_tts_smoke.wav")
  print(f"sr={sr} dur={len(data)/sr:.2f}s synth_time={time.time()-t0:.2f}s")
  assert sr == 44100, f"expected 44100, got {sr}"
  print("OK")
  ```

- [ ] **Step 3: Manual verification — Korean smoke (non-testable: needs the separate venv + model download).**
  Run: `~/jarvis/.venv-tts/bin/python ~/jarvis/scripts/tts_smoke.py`
  Expected observable: prints `sr=44100 dur=~4.x s synth_time=~1-3s` then `OK`; `afplay /tmp/jarvis_tts_smoke.wav` plays **intelligible Korean** ("안녕하세요. 저는 자비스입니다...").

- [ ] **Step 4: Manual verification — end-to-end worker from the MAIN venv (non-testable: live subprocess).** (`MeloTTSKR` spawns the `.venv-tts` worker with `PYTHONPATH=/Users/2seongjae/jarvis`, so no editable install in `.venv-tts` is needed.)
  Run:
  ```bash
  ~/jarvis/.venv/bin/python -c "import asyncio; from jarvis.tts.melotts_kr import MeloTTSKR; \
  t=MeloTTSKR(); t.warm(); import numpy as np, soundfile as sf; \
  p=asyncio.run(t.synth('자비스 음성 테스트입니다.')); \
  sf.write('/tmp/jarvis_worker.wav', p, t.sample_rate); \
  print('samples', p.shape, 'sr', t.sample_rate); t.close()"
  ```
  Expected: prints `samples (N,) sr 44100` with N≈ a few×10⁴; `afplay /tmp/jarvis_worker.wav` plays the same Korean sentence (proves main→.venv-tts IPC).

- [ ] **Step 5: Commit.** `cd ~/jarvis && git add -A && git commit -m "M2: .venv-tts MeloTTS+MeCab install recipe + Korean smoke script"`

---

### Task 11: `jarvis/vc/rvc.py` — `RVCConversion(VoiceConversion)` via mlx-rvc CLI (+ faiss/swig install)

**Files:**
- Create: `~/jarvis/jarvis/vc/rvc.py`
- Test: `~/jarvis/tests/vc/test_rvc.py`

- [ ] **Step 1: Verify RVC inference deps (main venv) — already installed via `.[voice]`.** `faiss-cpu>=1.7.2` and `mlx-rvc` come from the `[voice]` extra installed in Task 3 (`pip install -e ".[voice]"`; `brew install swig` was the faiss build prereq there) — do NOT re-run imperative `pip install`s. Verify:
  ```bash
  ~/jarvis/.venv/bin/python -c "import faiss; print(faiss.__version__)"   # prints >=1.7.2
  command -v mlx-rvc || ls ~/jarvis/.venv/bin/mlx-rvc                      # RVC CLI present (RVCConversion shells out to it)
  ```
  (Fallback timbre engine, A/B only: PyTorch-MPS fork NevilPatel01/RVC-WebUI-MacOS, swapped via `rvc_cmd`.)

- [ ] **Step 2: Write the failing test (fake RVC binary, no model needed).** Create `~/jarvis/tests/vc/test_rvc.py`:
  ```python
  import sys
  from pathlib import Path
  import numpy as np
  from jarvis.vc.rvc import RVCConversion


  def test_build_command_exact():
      vc = RVCConversion("m.pth", "m.index", sample_rate=40000,
                         index_rate=0.75, f0_up=0, f0_method="rmvpe")
      assert vc._build_command("in.wav", "out.wav") == [
          "mlx-rvc", "convert", "in.wav", "out.wav",
          "--model", "m.pth", "--index", "m.index",
          "--index-rate", "0.75", "--f0-method", "rmvpe", "--pitch", "0"]


  FAKE_RVC = (
      "import sys, numpy as np, soundfile as sf\n"
      "out_wav = sys.argv[3]\n"            # convert <in> <out> ...
      "sr = 40000\n"
      "t = np.arange(int(0.2 * sr)) / sr\n"
      "sf.write(out_wav, (0.1 * np.sin(2*np.pi*330*t)).astype('float32'), sr)\n"
  )


  def test_convert_runs_cli_and_resamples(tmp_path):
      fake = tmp_path / "fake_rvc.py"
      fake.write_text(FAKE_RVC)
      vc = RVCConversion("m.pth", "m.index", sample_rate=48000,
                         rvc_cmd=[sys.executable, str(fake)])
      out = vc.convert(np.zeros(44100, dtype=np.float32), in_rate=44100)
      assert out.dtype == np.float32
      # fake emits 0.2s @ 40000 -> resampled to 48000
      assert abs(out.shape[0] - int(0.2 * 48000)) <= 64
  ```

- [ ] **Step 3: Run & show expected FAIL.** `cd ~/jarvis && python -m pytest tests/vc/test_rvc.py -q` → **FAILS** `ModuleNotFoundError: jarvis.vc.rvc`.

- [ ] **Step 4: Minimal implementation.** Create `~/jarvis/jarvis/vc/rvc.py`:
  ```python
  """RVC voice conversion (JARVIS timbre). Primary: mlx-rvc CLI on Apple Silicon.
  Fallback (A/B only): PyTorch-MPS fork NevilPatel01/RVC-WebUI-MacOS — same
  .pth/.index, swap rvc_cmd. Validate timbre on 3 held-out clips vs the fork
  before committing index_rate/f0_up; mlx-rvc should match within perceptual tol.

  Model sample rate is per-.pth (40000 or 48000). convert() resamples the input
  to 40000 Hz (RVC ingest) via jarvis.audio.util.resample, runs inference (RMVPE
  f0), and returns float32 at self.sample_rate (the model's output rate). The
  orchestrator then resamples self.sample_rate -> playback_rate (48000)."""
  from __future__ import annotations
  import subprocess
  import tempfile
  from pathlib import Path
  import numpy as np

  from jarvis.audio.util import resample

  RVC_INGEST_RATE = 40000


  class RVCConversion:
      def __init__(self, model_path: str, index_path: str, sample_rate: int = 40000,
                   f0_method: str = "rmvpe", index_rate: float = 0.75,
                   f0_up: int = 0, rvc_cmd: list[str] | None = None):
          self.model_path = str(model_path)
          self.index_path = str(index_path)
          self.sample_rate = sample_rate
          self.f0_method = f0_method
          self.index_rate = index_rate
          self.f0_up = f0_up
          self._rvc_cmd = rvc_cmd or ["mlx-rvc"]

      def _build_command(self, in_wav: str, out_wav: str) -> list[str]:
          return [*self._rvc_cmd, "convert", in_wav, out_wav,
                  "--model", self.model_path, "--index", self.index_path,
                  "--index-rate", str(self.index_rate),
                  "--f0-method", self.f0_method, "--pitch", str(self.f0_up)]

      def warm(self) -> None:
          self.convert(np.zeros(int(0.5 * RVC_INGEST_RATE), dtype=np.float32), RVC_INGEST_RATE)

      def convert(self, pcm, in_rate: int, runner=subprocess.run) -> np.ndarray:
          import soundfile as sf
          x = np.asarray(pcm, dtype=np.float32).reshape(-1)
          if in_rate != RVC_INGEST_RATE:
              x = resample(x, in_rate, RVC_INGEST_RATE)
          with tempfile.TemporaryDirectory() as d:
              in_wav = str(Path(d) / "in.wav")
              out_wav = str(Path(d) / "out.wav")
              sf.write(in_wav, x, RVC_INGEST_RATE)
              runner(self._build_command(in_wav, out_wav), check=True)
              out, sr = sf.read(out_wav, dtype="float32")
          out = np.asarray(out, dtype=np.float32).reshape(-1)
          if sr != self.sample_rate:
              out = resample(out, sr, self.sample_rate)
          return out
  ```

- [ ] **Step 5: Run & show expected PASS.** `cd ~/jarvis && python -m pytest tests/vc/test_rvc.py -q` → **2 passed**.

- [ ] **Step 6: Manual verification — real RVC timbre (non-testable: needs the trained `.pth`+`.index`).** After Task 6 produces models in `~/jarvis/voice_models/`:
  ```bash
  ~/jarvis/.venv/bin/python -c "import numpy as np, soundfile as sf; \
  from jarvis.vc.rvc import RVCConversion; \
  p,sr=sf.read('/tmp/jarvis_tts_smoke.wav', dtype='float32'); \
  vc=RVCConversion('$HOME/jarvis/voice_models/jarvis.pth','$HOME/jarvis/voice_models/jarvis.index', sample_rate=40000); \
  o=vc.convert(p, sr); sf.write('/tmp/jarvis_rvc.wav', o, vc.sample_rate); print('out', o.shape, vc.sample_rate)"
  ```
  Expected: writes `/tmp/jarvis_rvc.wav`; `afplay /tmp/jarvis_rvc.wav` plays the same Korean words **in JARVIS timbre** (distinct from the MeloTTS voice).

- [ ] **Step 7: Commit.** `cd ~/jarvis && git add -A && git commit -m "M2: RVCConversion via mlx-rvc CLI (RMVPE, resample 44.1k->40k->target) + faiss/swig"`

---

### Task 12: Config-driven backend selection + orchestrator wiring

**Files:**
- Modify: `~/jarvis/jarvis/core/config.py` (add M2 backend fields to `Settings`)
- Create: `~/jarvis/jarvis/tts/factory.py`
- Create: `~/jarvis/jarvis/vc/factory.py`
- Modify: `~/jarvis/jarvis/__main__.py` (build TTS/VC via `make_tts`/`make_vc` in `build_orchestrator`; `Orchestrator.__init__` stays untouched)
- Test: `~/jarvis/tests/tts/test_factory.py`, `~/jarvis/tests/vc/test_factory.py`, `~/jarvis/tests/core/test_config_m2.py`

- [ ] **Step 1: Write the failing tests.** Create `~/jarvis/tests/core/test_config_m2.py`:
  ```python
  from jarvis.core.config import Settings


  def test_m2_backend_defaults():
      f = Settings.model_fields
      assert f["tts_backend"].default == "say"
      assert f["vc_backend"].default == "null"
      assert f["rvc_sample_rate"].default == 40000
  ```
  Create `~/jarvis/tests/tts/test_factory.py`:
  ```python
  import types, pytest
  from jarvis.tts.factory import make_tts
  from jarvis.tts.system_say import SystemSayTTS
  from jarvis.tts.melotts_kr import MeloTTSKR


  def _s(**kw):
      base = dict(tts_backend="say", tts_worker_python="~/jarvis/.venv-tts/bin/python")
      base.update(kw); return types.SimpleNamespace(**base)


  def test_make_tts_say():
      assert isinstance(make_tts(_s(tts_backend="say")), SystemSayTTS)


  def test_make_tts_melotts():
      tts = make_tts(_s(tts_backend="melotts"))
      assert isinstance(tts, MeloTTSKR) and tts._cmd[1:] == ["-m", "jarvis.tts.tts_worker"]


  def test_make_tts_unknown_raises():
      with pytest.raises(ValueError):
          make_tts(_s(tts_backend="bogus"))
  ```
  Create `~/jarvis/tests/vc/test_factory.py`:
  ```python
  import types, pytest
  from jarvis.vc.factory import make_vc
  from jarvis.vc.null_vc import NullVC
  from jarvis.vc.rvc import RVCConversion


  def _s(**kw):
      base = dict(vc_backend="null",
                  rvc_model_path="~/jarvis/voice_models/jarvis.pth",
                  rvc_index_path="~/jarvis/voice_models/jarvis.index",
                  rvc_sample_rate=40000, rvc_index_rate=0.75, rvc_f0_up=0)
      base.update(kw); return types.SimpleNamespace(**base)


  def test_make_vc_null():
      assert isinstance(make_vc(_s(vc_backend="null")), NullVC)


  def test_make_vc_rvc_when_model_present(tmp_path):
      pth = tmp_path / "jarvis.pth"; pth.write_bytes(b"x")
      idx = tmp_path / "jarvis.index"; idx.write_bytes(b"x")
      vc = make_vc(_s(vc_backend="rvc", rvc_model_path=str(pth), rvc_index_path=str(idx)))
      assert isinstance(vc, RVCConversion) and vc.sample_rate == 40000 and vc.index_rate == 0.75


  def test_make_vc_rvc_falls_back_to_null_when_model_absent(tmp_path):
      # spec 8.4 bootstrap: the JARVIS voice path must run BEFORE Colab produces jarvis.pth.
      vc = make_vc(_s(vc_backend="rvc", rvc_model_path=str(tmp_path / "absent.pth")))
      assert isinstance(vc, NullVC)


  def test_make_vc_unknown_raises():
      with pytest.raises(ValueError):
          make_vc(_s(vc_backend="bogus"))
  ```

- [ ] **Step 2: Run & show expected FAIL.** `cd ~/jarvis && python -m pytest tests/core/test_config_m2.py tests/tts/test_factory.py tests/vc/test_factory.py -q` → **FAILS** (`KeyError: 'tts_backend'` in config test; `ModuleNotFoundError: jarvis.tts.factory` / `jarvis.vc.factory`).

- [ ] **Step 3: Add the Settings fields.** In `~/jarvis/jarvis/core/config.py`, inside the `Settings` class body, add these fields (alongside the existing M1 fields):
  ```python
      tts_backend: str = "say"          # "say" (macOS say, M1 backend) | "melotts" (M2)
      vc_backend: str = "null"          # "null" (identity, M1 backend) | "rvc" (M2)
      tts_worker_python: str = "~/jarvis/.venv-tts/bin/python"
      rvc_model_path: str = "~/jarvis/voice_models/jarvis.pth"
      rvc_index_path: str = "~/jarvis/voice_models/jarvis.index"
      rvc_sample_rate: int = 40000
      rvc_index_rate: float = 0.75
      rvc_f0_up: int = 0
  ```

- [ ] **Step 4: Create the factories.** Create `~/jarvis/jarvis/tts/factory.py`:
  ```python
  """Config-driven TTS backend selection."""
  from __future__ import annotations
  import os
  from jarvis.tts.base import TTSBackend


  def make_tts(settings) -> TTSBackend:
      backend = settings.tts_backend
      if backend == "say":
          from jarvis.tts.system_say import SystemSayTTS
          return SystemSayTTS()
      if backend == "melotts":
          from jarvis.tts.melotts_kr import MeloTTSKR
          worker_python = os.path.expanduser(settings.tts_worker_python)
          return MeloTTSKR(worker_cmd=[worker_python, "-m", "jarvis.tts.tts_worker"])
      raise ValueError(f"unknown tts_backend: {backend!r}")
  ```
  Create `~/jarvis/jarvis/vc/factory.py`:
  ```python
  """Config-driven voice-conversion backend selection."""
  from __future__ import annotations
  import logging
  import os

  from jarvis.vc.base import VoiceConversion

  _log = logging.getLogger(__name__)


  def make_vc(settings) -> VoiceConversion:
      backend = settings.vc_backend
      if backend == "null":
          from jarvis.vc.null_vc import NullVC
          return NullVC()
      if backend == "rvc":
          from jarvis.vc.null_vc import NullVC
          from jarvis.vc.rvc import RVCConversion
          model_path = os.path.expanduser(settings.rvc_model_path)
          index_path = os.path.expanduser(settings.rvc_index_path)
          if not os.path.exists(model_path):
              # spec 8.4 bootstrap: the JARVIS voice path must run BEFORE Colab training
              # produces jarvis.pth. Fall back to identity passthrough so the MeloTTS
              # voice still plays (no timbre conversion yet).
              _log.warning(
                  "vc_backend='rvc' but model %s is absent; falling back to NullVC "
                  "(run voice_training -> Colab to produce jarvis.pth + .index).",
                  model_path)
              return NullVC()
          return RVCConversion(
              model_path=model_path,
              index_path=index_path,
              sample_rate=settings.rvc_sample_rate,
              index_rate=settings.rvc_index_rate,
              f0_up=settings.rvc_f0_up)
      raise ValueError(f"unknown vc_backend: {backend!r}")
  ```

- [ ] **Step 5: Run & show expected PASS.** `cd ~/jarvis && python -m pytest tests/core/test_config_m2.py tests/tts/test_factory.py tests/vc/test_factory.py -q` → **8 passed**.

- [ ] **Step 6: Wire backend selection at the DI site (`build_orchestrator`), NOT in `Orchestrator.__init__`.** `Orchestrator.__init__(self, *, settings, activator, capture, stt, brain, chunker, tts, vc, playback)` is keyword-only dependency injection and NEVER constructs backends itself — all backend construction lives in `~/jarvis/jarvis/__main__.py::build_orchestrator`. So the wiring change targets `jarvis/__main__.py`, leaving `Orchestrator` untouched:
  1. Replace the M1 backend imports
     ```python
     from .tts.system_say import SystemSayTTS
     from .vc.null_vc import NullVC
     ```
     with the factories
     ```python
     from .tts.factory import make_tts
     from .vc.factory import make_vc
     ```
  2. Inside `build_orchestrator(...)`, replace the M1 backend construction passed into `Orchestrator(...)`
     ```python
         tts=SystemSayTTS(voice="Yuna"),
         vc=NullVC(sample_rate=settings.playback_rate),
     ```
     with
     ```python
         tts=make_tts(settings),
         vc=make_vc(settings),
     ```
  No other change: `Orchestrator` still resamples `self.tts.sample_rate -> RVC ingest` inside `vc.convert`, then `self.vc.sample_rate -> settings.playback_rate (48000)` before the playback ring buffer, and barge-in still cancels the Brain pipeline Task + `playback.abort()`. With default settings (`tts_backend="say"`, `vc_backend="null"`), `make_tts`/`make_vc` return `SystemSayTTS()` / `NullVC()`, so the M1 `tests/test_main_wiring.py::test_build_orchestrator_wires_all_components` stays green; re-run it now to confirm: `cd ~/jarvis && python -m pytest tests/test_main_wiring.py -q` → **1 passed**.

- [ ] **Step 7: Manual verification — full M2 path (non-testable: live audio + models).** `Orchestrator.__init__` is keyword-only DI, so it can NOT be constructed from a bare `Settings` — run the real entrypoint, which goes through `build_orchestrator()` and supplies every component. `Settings` is `pydantic-settings` with `env_prefix="JARVIS_"`, so the backends are selected from the environment:
  ```bash
  JARVIS_TTS_BACKEND=melotts JARVIS_VC_BACKEND=rvc ~/jarvis/.venv/bin/python -m jarvis
  ```
  Hold Right-Option, say "오늘 서울 날씨 알려줘", release. Expected observable: a spoken Korean answer **in JARVIS timbre** plays through the 48 kHz output (or the plain MeloTTS voice if `~/jarvis/voice_models/jarvis.pth` is not trained yet — `make_vc` logs the NullVC bootstrap fallback, spec 8.4); speaking again mid-reply (barge-in) cuts the audio immediately.

- [ ] **Step 8: Commit.** `cd ~/jarvis && git add -A && git commit -m "M2: config-driven TTS/VC factories + orchestrator wiring (MeloTTSKR + RVC)"`

---

### Task 13: Latency measurement on M4 Pro (manual verification)

**Files:**
- Create: `~/jarvis/scripts/measure_latency_m2.py`

- [ ] **Step 1: Author the measurement script.** Create `~/jarvis/scripts/measure_latency_m2.py`:
  ```python
  """M2 voice latency on M4 Pro. Run from the MAIN venv (needs .venv-tts ready
  and ~/jarvis/voice_models/jarvis.pth + .index present):
      ~/jarvis/.venv/bin/python scripts/measure_latency_m2.py
  """
  import asyncio
  import time
  from jarvis.core.config import Settings
  from jarvis.tts.factory import make_tts
  from jarvis.vc.factory import make_vc


  async def main():
      s = Settings(tts_backend="melotts", vc_backend="rvc")
      tts = make_tts(s)
      vc = make_vc(s)
      tts.warm(); vc.warm()                              # exclude cold-start
      text = "지금 서울의 날씨는 맑고 기온은 이십삼 도입니다."
      t0 = time.time(); pcm = await tts.synth(text);  t1 = time.time()
      conv = vc.convert(pcm, tts.sample_rate);        t2 = time.time()
      dur = len(conv) / vc.sample_rate
      print(f"text_chars={len(text)} audio_dur={dur:.2f}s")
      print(f"tts={t1-t0:.2f}s ({(t1-t0)/dur:.2f}x RT)  "
            f"vc={t2-t1:.2f}s ({(t2-t1)/dur:.2f}x RT)  total={t2-t0:.2f}s")
      tts.close()


  if __name__ == "__main__":
      asyncio.run(main())
  ```

- [ ] **Step 2: Manual verification (non-testable: hardware-dependent timing).**
  Run: `~/jarvis/.venv/bin/python ~/jarvis/scripts/measure_latency_m2.py`
  Expected observable on M4 Pro 24 GB: `audio_dur≈3–4s`; `tts≈1.0–2.0s (~0.3–0.6x RT)`; `vc≈0.6–1.5s (~0.2–0.5x RT)`; `total < ~3.5s` and below `audio_dur`, so with the M1 `SentenceChunker` feeding one clause at a time the first spoken clause begins well under ~2.5 s. Record the printed numbers in the PR description as the M2 latency baseline.

- [ ] **Step 3: Commit.** `cd ~/jarvis && git add -A && git commit -m "M2: M4 Pro voice latency measurement script + recorded baseline"`