# Stage 1 report: skeleton

- Date: 2026-11-17
- Git commit: not applicable yet (no git repository; repo-keeper creates it in stage 1b)
- Prompt in force: Stage 1 task from the coordinator (CLAUDE.md section 4, stage 1 row)
- Related reports: `reports/01_audit.md`

Terms: a **venv** is a self-contained Python environment (here `.venv/`). **uv** is a fast Python installer and environment tool. **pytest** is the Python test runner. A **stub** is a function with the agreed name and signature that only raises "not implemented"; a later stage fills it in. **Idempotent** means running it twice is safe and gives the same result.

## What was built (all inside `~/omni_recorder/`)

| file | purpose |
|---|---|
| `scripts/env.sh` | Sourceable. Sets `OMNI_ROOT`, `HF_HOME`, `XDG_CACHE_HOME`, `PIP_CACHE_DIR`, `TMPDIR`, `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR` inside the project, creates those folders, prepends `.venv/bin` to `PATH`. Does not set `HF_HUB_OFFLINE`. |
| `scripts/setup.sh` | Sources env.sh, creates `.venv` with Python 3.12 (downloaded by uv into `.cache/uv-python`), installs the package with the `dev` extra. Idempotent. |
| `scripts/prepush_check.sh` | Privacy gate per CLAUDE.md section 8. Looks at tracked plus staged files (works with zero commits), rejects private folders, audio/video extensions, model files, files over 1 MB, transcript-like names outside `tests/fixtures/`, and a missing `git config --local user.email`. Exit 1 with the offending files listed, else exit 0. Optional argument: a repo path (used by the tests). |
| `pyproject.toml` | Package `omni_recorder`, src layout, console script `omni-rec`, Python `>=3.11,<3.14`, no runtime dependencies, `dev` extra = pytest. |
| `config.toml` | Sections `[paths]`, `[audio]`, `[languages]`, `[speech]`, `[translation]`, `[llm]`. Speech, translation and LLM model fields are empty placeholders for stages 3 and 4. |
| `src/omni_recorder/__init__.py` | Sets `HF_HUB_OFFLINE=1` (and `TRANSFORMERS_OFFLINE=1`) with `setdefault` before anything else loads. |
| `src/omni_recorder/config.py` | Loads `config.toml` with `tomllib`; relative paths resolve against the project root; `$OMNI_CONFIG` overrides the file path (used by tests). |
| `src/omni_recorder/paths.py` | `new_call_id()` (`YYYY-MM-DD_HHMM`, then `_2`, `_3`), `list_call_ids()`. |
| `src/omni_recorder/calls.py` | Which steps are done for a call folder, judged by which output files exist. |
| `src/omni_recorder/cli.py` | `omni-rec` with start, stop, status, list, process (+ flags), doctor, watch. `start` prints the consent reminder, then exits 2 ("not implemented until stage 2"). stop/status: stage 2, process: stage 3, watch: stage 6; all exit 2. `list` and `doctor` work. |
| `src/omni_recorder/doctor.py` | Tool, GPU, Python, config, env-var and models-folder checks with an OK/WARN/FAIL table; exit 0 if no FAIL. Contains the marked hook `cleanup_leftovers()` (does nothing yet, stage 2). |
| `src/omni_recorder/recorder.py` | Stubs for audio-engineer: `start_recording`, `stop_recording`, `recording_status`. |
| `src/omni_recorder/speech.py` | Stubs for speech-engineer: `transcribe_call`, `translate_call`. |
| `src/omni_recorder/scripting.py` | Stubs for script-writer: `make_notes`, `make_highlights`, `make_video_brief`. |
| `tests/` | `conftest.py`, `test_paths.py`, `test_config.py`, `test_cli.py`, `test_prepush_check.py`. |
| `README.md` | What it is, setup, commands, privacy and consent notice. |

`.gitignore` already covered everything needed; it was not changed.

## Commands run and results

1. `bash scripts/setup.sh`: downloaded CPython 3.12.16 into `.cache/uv-python`, created `.venv`, installed `omni-recorder 0.1.0` (editable) plus pytest 9.2.0, pluggy, iniconfig, packaging, pygments. Exit 0. A second run reused `.venv` and exited 0.
2. `source scripts/env.sh && omni-rec doctor`: 16 OK, 0 WARN, 0 FAIL, exit 0. It reported ffmpeg n9.0.2, pactl 17.0, libpipewire 1.6.9 (pw-record/pw-dump/pw-link), git 2.56.0, gh 2.103.3, GPU NVIDIA GeForce RTX 3070 with 6569 MiB free of 8192 MiB, Chrome at `/usr/bin/google-chrome-stable`, Python 3.12.16 in the project `.venv`. With the four cache variables removed from the environment, doctor gives one WARN ("run: source scripts/env.sh") and still exits 0.
3. `source scripts/env.sh && pytest -q`: 49 passed in about 0.6 s.
4. prepush_check.sh tests (inside `tests/test_prepush_check.py`, part of the 49): each throwaway git repo is created under the project `.tmp/` with zero commits and synthetic content only. Verified REJECT for a fake `records/x.txt`, a fake `.flac`, upper-case `.WAV`, `.mp4`, files under `models/ .venv/ .cache/ .tmp/ vendor/`, `.gguf .safetensors .onnx .pt .bin`, `transcript.json`, `transcript_en.md`, `notes.md`, `highlights.json`, `video_brief.md/.json`, a 2 MB file, an already-committed bad file, a file name with spaces, and a missing local `user.email`. Verified PASS for a clean repo, an empty repo, transcript-like names under `tests/fixtures/`, and an ignored untracked `records/` file.

## What the result means

The acceptance check for stage 1 passes: `omni-rec doctor` runs and exits 0, and the tests are green. The privacy gate rejects what CLAUDE.md section 8 lists. I have not run `prepush_check.sh` against the real project because it is not yet a git repository; repo-keeper should run it before the first push.

## Problems and assumptions

- No signature contract for the stubs existed, so I chose simple ones: `fn(cfg: Config, call_path: Path) -> Path` for the speech and script stages, and `start_recording(cfg) -> call_id`, `stop_recording(cfg) -> Path`, `recording_status(cfg) -> str | None`. Owners may adjust them; keep `cli.py` in step.
- `HF_HUB_OFFLINE` is set with `setdefault`, so a setup/download step must export `HF_HUB_OFFLINE=0` explicitly. Without that, any Python process that imports `omni_recorder` stays offline.
- `wpctl` does not report a version, so doctor says "present". `pw-record`, `pw-dump`, `pw-link` report the libpipewire version only.
- Doctor severities: FAIL if ffmpeg, ffprobe, pw-record or pactl is missing; WARN for the other tools, GPU, Chrome, env vars and models folder.
- Python 3.12 is used, not the system 3.14.8, because it is the safer target for faster-whisper, CTranslate2 and torch wheels in stage 3 (assumption, not tested yet).
- No shell command was denied. `cmake` and `python-pip` from the audit are not needed for this stage.

## Installed on this system

System packages: nothing (`reports/INSTALLED.md` unchanged).

Python packages in `.venv` (project-local, Python 3.12.16): omni-recorder 0.1.0 (editable, this project), pytest 9.2.0, pluggy 1.7.0, iniconfig 2.3.1, packaging 26.3, pygments 2.21.0. Python interpreter CPython 3.12.16 downloaded by uv into `.cache/uv-python`.
