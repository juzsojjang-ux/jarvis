# voice_models/ — drop the JARVIS voice here

This is the **only** thing you have to do to give JARVIS its real voice.

## How (one step)

Put your trained RVC model into this folder:

```
voice_models/
  jarvis.pth                 # required — the trained RVC voice model
  added_*.index              # optional — improves timbre similarity (any name)
```

- The **`.pth` is required.** If you name it `jarvis.pth` it's picked up by name;
  any other `*.pth` in this folder is auto-detected too.
- The **`.index` is optional.** `added_<hash>.index` (RVC's default export name) or any
  `*.index` here is found automatically. Without an index, conversion still works.

That's it. On the next launch JARVIS detects the model and **automatically** speaks in
the JARVIS timbre (`vc_backend="auto"`). Ask it "내 목소리 지금 자비스로 나와?" any time —
the `voice_status` tool reports the live state.

## The one prerequisite (one-time, already automatable)

JARVIS converts timbre with an isolated RVC runtime in `.venv-rvc`. Install it once:

```bash
bash voice_training/setup_rvc.sh
```

Until that runtime exists, JARVIS keeps speaking in the MeloTTS Korean voice and the
status line tells you exactly what's missing. After it exists **and** `jarvis.pth` is
here, the JARVIS voice turns on by itself — no code or config changes.

## Notes
- Files here are personal/local only — **not** committed to git (see `.gitignore`).
- Model sample rate (40 kHz / 48 kHz) is read from the `.pth`; `JARVIS_RVC_SAMPLE_RATE`
  / `JARVIS_RVC_INDEX_RATE` / `JARVIS_RVC_F0_UP` override conversion params if needed.
- Inference device: `JARVIS_RVC_DEVICE` (default `mps`; set `cpu` if MPS misbehaves).
