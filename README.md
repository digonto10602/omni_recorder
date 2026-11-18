# omni_recorder

A local call recorder and script maker for Linux (PipeWire audio). It records Facebook Messenger calls made in Chrome, transcribes them (Bengali and English, including mixed speech), writes notes, cuts out the interesting parts as clips, and produces a "video brief" (scene and frame descriptions) that can later be given to a video-making AI model.

Everything runs on your own machine. No cloud speech or language-model service is ever called. The app sets `HF_HUB_OFFLINE=1` (Hugging Face's "never go online" switch) and makes no network calls; the network is used only during setup (Python packages, model files) and for `git push`.

Status: recording works (`start`, `stop`, `status`, `list`, `doctor`, `manual`, `keys`). Transcription, translation, notes, clips and the video brief (`process`, stages 3-5) and `watch` (stage 6) are not built yet; those commands say "not implemented until stage N".

**Full user manual: [docs/MANUAL.md](docs/MANUAL.md)** (or run `omni-rec manual`). One-screen cheat sheet: `omni-rec keys`, or the desktop shortcut Ctrl+Shift+Alt+H.

## Privacy and consent notice

- **You are responsible for consent.** Tell the other person the call is being recorded, and get their agreement. You are also responsible for getting consent before reusing someone's words or voice in generated videos. Laws on recording calls differ by country. `omni-rec start` prints a reminder every time; do not remove it.
- Recordings are private. `records/`, `models/`, `.venv/`, `.cache/` and `.tmp/` are git-ignored, and `scripts/prepush_check.sh` refuses to let audio, transcripts, notes, model files or files over 1 MB be pushed. This repository is public, so never put real call content in tests, reports, prompts or the README.

## Setup

Requirements: Linux with PipeWire, `ffmpeg`, `uv`, `git`. Nothing is installed outside this folder.

```
cd ~/omni_recorder
bash scripts/setup.sh            # creates .venv (Python 3.12, downloaded by uv into .cache/), installs the package
source scripts/env.sh            # in every new shell: keeps caches and temp files inside the project
omni-rec doctor
```

`scripts/env.sh` sets `HF_HOME`, `XDG_CACHE_HOME`, `PIP_CACHE_DIR`, `TMPDIR`, `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR` to folders inside the project and puts `.venv/bin` on `PATH`.

## Commands

```
omni-rec start                 # begin recording (prints consent reminder)
omni-rec stop                  # stop, finalize files
omni-rec status                # is a recording running?
omni-rec list                  # list calls and which steps are done
omni-rec process <call_id>     # transcribe + translate + notes      [planned: stage 3-5]
        --no-translate --highlights --brief --all
omni-rec doctor                # check tools, GPU, config; clean up after a crash
omni-rec watch                 # auto start/stop on a Chrome call    [planned: stage 6]
omni-rec manual                # read the full manual
omni-rec keys                  # cheat sheet + recording status (alias: cheatsheet)
```

Each call lives in `records/<YYYY-MM-DD_HHMM>/` (`_2`, `_3` added if two calls share a minute). Every option, output file, warning and fix is explained in [docs/MANUAL.md](docs/MANUAL.md).

## Configuration

`config.toml` holds paths, audio targets, allowed languages and model names. Model names are never hard-coded in Python, so a better speech model or a different language model can be swapped in by editing the file. Speech and translation model fields are blank until the Stage 3 comparison picks winners.

## Tests and the privacy check

```
source scripts/env.sh
pytest -q
bash scripts/prepush_check.sh    # run before every push
```
