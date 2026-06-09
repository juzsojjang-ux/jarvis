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

## MeloTTS voice worker (`.venv-tts`, macOS — validated on M4 Pro)
MeloTTS runs in an isolated `.venv-tts` (it pins old torch/transformers). macOS is
case-insensitive, so `mecab-python3` (the `MeCab` package, used by MeloTTS's Japanese
module) and `python-mecab-ko` (the `mecab` package, used by Korean g2pkk) map to the
SAME directory and cannot coexist. We build Korean-only:
```bash
python3.11 -m venv .venv-tts
.venv-tts/bin/pip install "git+https://github.com/myshell-ai/MeloTTS.git" \
    soundfile==0.13.1 python-mecab-ko
.venv-tts/bin/pip uninstall -y mecab-python3            # collides with python-mecab-ko
.venv-tts/bin/python voice_training/patch_melotts.py    # Japanese import -> optional (Korean-only)
```
The TTS worker (`jarvis/tts/tts_worker.py`) redirects MeloTTS/tqdm noise to stderr so it
never corrupts the binary IPC stdout. Smoke test (from the main venv): `MeloTTSKR().warm()`
then `synth("안녕하세요")` returns 44100 Hz float32 (~6.7 s for a short sentence).
