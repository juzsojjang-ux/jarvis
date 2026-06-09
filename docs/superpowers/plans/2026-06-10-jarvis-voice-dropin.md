# Plan: JARVIS voice drop-in readiness

Goal (user): "내가 자비스 파일만 구해서 주면 모든게 완성되게" — the moment a trained
JARVIS RVC model is placed in `voice_models/`, the assistant speaks in the JARVIS
timbre automatically. The user's ONLY remaining action is to drop the file.

Copyright boundary (unchanged): I do NOT download copyrighted JARVIS audio and do NOT
run Colab training. The user supplies `jarvis.pth` (+ optional `added_*.index`).

## Split

A. Deterministic wiring (this branch, fully unit-tested) — makes "drop file → on"
   true *given a runtime*:
   1. `vc_backend="auto"` (new default): model present ⇒ RVC, absent ⇒ MeloTTS voice.
   2. Index auto-resolution: configured path, else `added_*.index`/`*.index` glob next
      to the model. Index is OPTIONAL (RVC runs on the .pth alone).
   3. Model auto-resolution: exact `jarvis.pth`, else first `*.pth` in `voice_models/`.
   4. Runtime gate: only switch to RVC when BOTH the model AND the isolated runtime
      interpreter (`.venv-rvc`) exist; otherwise stay on MeloTTS with a clear message.
   5. Startup status banner + `voice_status` tool ("내 목소리 자비스로 켜졌어?").
   6. `voice_models/` drop-in directory + precise README.
   7. Runtime-agnostic adapter shim `jarvis/vc/rvc_infer_cli.py` exposing our stable
      `convert <in> <out> --model ... [--index ...] --index-rate --f0-method --pitch`
      contract; the factory wires `rvc_cmd = [.venv-rvc/bin/python, shim]`.
   8. End-to-end fake-model test: drop a fake `.pth` + fake CLI ⇒ orchestrator
      `_speak` flows through RVC convert and yields playable audio.

B. Runtime (environment-fragile; one-command bootstrap + best-effort attempt):
   `.venv-rvc` on python3.11 + `rvc-python` with the One-sixth/fairseq fork (classic
   fairseq needs <3.11) + base models (hubert/rmvpe auto-download). Script:
   `voice_training/setup_rvc.sh`. Verified as far as the environment allows; if it
   can't finish autonomously, the wiring is still complete and one script remains.

## Runtime research (2026-06)
- `rvc-python` (PyPI 0.1.5): clean CLI `rvc infer`, but `fairseq==0.12.2` + `numpy<=1.23.5`,
  fairseq needs Python <3.11. → isolate in `.venv-rvc`; use One-sixth/fairseq fork to
  build on 3.11.
- `infer-rvc-python`, `rvc-infer`, `rvc-inferpy`: all also fairseq-based.
- Conclusion: isolated venv is mandatory (mirrors `.venv-tts`); the shim decouples us
  from any specific runtime's API.

## Pipeline (unchanged shape)
`_speak`: tts.synth → vc.convert(audio, tts.sample_rate) → resample(vc.sample_rate →
playback_rate) → playback.feed. RVCConversion.convert resamples input → 40 kHz, runs
the shim, returns float32 at the model's output rate.
