# omni_recorder

Local call recorder and script maker for the desktop `omnicommander` (Omarchy: Arch Linux + Hyprland, PipeWire audio).

It records Facebook Messenger calls made in Chrome, transcribes them (Bengali and English, including mixed speech), writes notes, cuts the interesting parts into clips, and produces a "video brief" (scene and frame descriptions) that can later be handed to a video-making AI model.

Everything runs on this machine. No cloud speech or LLM service is ever called.

---

## 1. Hard rules (never break these)

1. **Stay inside `~/omni_recorder/`.** Create, edit and delete files only here. Nothing outside this folder may be edited by hand: no `~/.config`, no `~/.bashrc`, no `/etc`, no systemd units, no global git config. The single exception is installing system packages under rule 3.
2. **Outside programs may be used, not changed.** Running `ffmpeg`, `pw-record`, `pactl`, `git`, `gh`, `python`, `nvidia-smi` and similar is fine. Reconfiguring, upgrading or removing programs that are already installed is not.
3. **Installing missing system packages is allowed without asking the user.** Any agent may install a package its task needs. Limits:
   - Install only: `sudo pacman -S --needed <package>`, or, when the agent cannot type a sudo password, `pkexec pacman -S --needed <package>` (the user types the password into the graphical pop-up; approved by the user on 2026-11-17). Official Arch repositories first; the AUR (the Arch User Repository, community-maintained build scripts) through `yay` only when no official package exists.
   - Never remove or downgrade a package, never run a full system upgrade (`pacman -Syu`), never use `pacman -Sy` on its own, never `systemctl enable` or start a new system service, never edit a config file the package put outside this folder. If an install only works after a full system upgrade, stop and ask the user.
   - Install the smallest thing that does the job; do not install something already present.
   - **Log every install** by appending a line to `reports/INSTALLED.md`: date, package, version, source (official or AUR), which agent, and why.
   - **Show the list.** Every result shown to the user in the terminal ends with an "Installed on this system" section listing every package installed so far in the project (from `reports/INSTALLED.md`), with the ones from this step marked as new. If nothing has been installed yet, say "nothing".
   - If `sudo` asks for a password the agent cannot type, do not try to get around it: put the exact command in `reports/NEEDS_USER.md`, tell the user, and stop that stage.
4. **Keep all caches and downloads inside the project.** Every command runs with the environment from `scripts/env.sh`:
   - `HF_HOME=~/omni_recorder/models/hf`
   - `XDG_CACHE_HOME=~/omni_recorder/.cache`
   - `PIP_CACHE_DIR=~/omni_recorder/.cache/pip`
   - `TMPDIR=~/omni_recorder/.tmp`
   - Python packages go only into `~/omni_recorder/.venv`.
5. **Audio server: no persistent changes.** Do not write PipeWire or WirePlumber config. Any runtime-only object (a link, a loopback) created while recording must be removed when recording stops, including after a crash (`omni-rec doctor` cleans up).
6. **Fully local at run time.** Network is allowed only (a) during setup to download Python packages and model files, and (b) for `git push`. The app itself sets `HF_HUB_OFFLINE=1` and makes no network calls.
7. **Recordings are private. The GitHub repo is public.** `records/`, `models/`, `.venv/`, `.cache/`, `.tmp/` and any audio or transcript file must never be committed. `scripts/prepush_check.sh` must pass before every push (see section 8).
8. **Consent.** The app prints a reminder at `omni-rec start` that the other person should know the call is recorded. Do not remove it. The README must state that the user is responsible for consent, both for recording and for reusing someone's words or voice in generated videos.
9. **Git identity is repo-local only:** `git config --local`. Never `--global`.

If a task cannot be done without breaking a rule, stop and ask the user.

**Approved exception to rule 1 (user, 2026-11-17):** one key binding in `~/.config/hypr/bindings.lua` (Ctrl+Shift+Alt+H) that shows the `omni-rec keys` cheat sheet. Nothing else outside the project.

**Manual:** `docs/MANUAL.md` is the full user manual and the cheat sheet (`omni-rec keys`) is its short form. Every stage that adds or changes a command or an output file updates both in the same commit.

---

## 2. What the app does (pipeline)

```
record  ->  transcribe  ->  notes  ->  highlights + clips  ->  video brief
```

| Step | Tool | Output in `records/<call_id>/` |
|---|---|---|
| Record | `pw-record` / `ffmpeg` on PipeWire | `me.flac`, `them.flac`, `mix.flac`, `meta.json` |
| Transcribe | winner of the Bengali bake-off (section 4a), run through faster-whisper where possible | `transcript.json`, `transcript.md` |
| Translate | winner of the translation test (section 4a) | `transcript_en.json`, `transcript_en.md` (every Bengali segment with its English translation; English segments copied unchanged) |
| Notes | local LLM through llama.cpp | `notes.md` |
| Highlights | local LLM picks time ranges, `ffmpeg` cuts them | `highlights.json`, `clips/NN_slug.flac`, `clips/NN_slug.md` |
| Video brief | local LLM | `video_brief.md`, `video_brief.json` |

`<call_id>` is `YYYY-MM-DD_HHMM` (add `_2`, `_3` on collision).

Design decisions already made:

- **Two separate tracks.** `me.flac` is the microphone, `them.flac` is Chrome's sound output. This gives speaker labels for free, with no speaker-separation model.
- **Capture Chrome only** when possible (target Chrome's audio stream node). Fall back to the default output monitor (all system sound) and say so in `meta.json`.
- **Language is detected per speech chunk**, restricted to Bengali (`bn`) and English (`en`), so a call that switches language is handled chunk by chunk. Each transcript segment stores `start`, `end`, `speaker`, `lang`, `text`.
- **Models are loaded only when needed and one at a time.** Whisper is unloaded before the LLM is loaded. Nothing stays in GPU memory after a command finishes.
- **Model names live in `config.toml`,** never hard-coded, so a better Bengali speech model or a different LLM can be swapped in without code changes.
- **The audio is the source of truth.** Transcripts of Bengali will contain errors. Every note, highlight and brief item carries timestamps pointing back to the audio.

### Command line

```
omni-rec start                 # begin recording (prints consent reminder)
omni-rec stop                  # stop, finalize files
omni-rec status                # is a recording running?
omni-rec list                  # list calls and which steps are done
omni-rec process <call_id>     # transcribe + translate to English + notes (default)
        --no-translate         # skip the English translation file
        --highlights           # also pick and cut interesting parts
        --brief                # also write the video brief
        --all                  # everything
omni-rec doctor                # check tools, GPU, models; clean leftovers
omni-rec watch                 # (stage 6, optional) auto start/stop when a Chrome call is detected
```

---

## 3. Folder layout

```
~/omni_recorder/
├── CLAUDE.md
├── README.md
├── config.toml               # models, languages, audio targets
├── pyproject.toml
├── .gitignore
├── .claude/agents/           # project agents (section 5)
├── prompts/
│   ├── build/                # numbered work prompts for Claude agents
│   └── llm/                  # numbered prompts used by the local LLM at run time
├── reports/                  # numbered reports from agents; INSTALLED.md; NEEDS_USER.md
├── scripts/                  # env.sh, prepush_check.sh, setup.sh
├── src/omni_recorder/        # the app (Python)
├── tests/
├── records/                  # PRIVATE, git-ignored
├── models/                   # PRIVATE, git-ignored (Whisper + LLM files)
└── .venv/ .cache/ .tmp/      # git-ignored
```

Numbering: prompts and reports are named `NN_short_name.md`, counting up, never renumbered.

---

## 4. Build stages

Work through the stages in order. Each stage ends with a numbered report in `reports/` and a commit. Do not start a stage until the previous acceptance check passes.

| # | Stage | Owner | Acceptance check |
|---|---|---|---|
| 0 | Audit the machine: which tools exist, GPU and its memory, PipeWire version, Python version, `gh` login | runner | `reports/01_audit.md` lists everything; missing tools are installed under rule 3 and logged in `reports/INSTALLED.md` |
| 1 | Skeleton: `scripts/env.sh`, `.venv`, package layout, `config.toml`, CLI stub, `prepush_check.sh` | builder | `omni-rec doctor` runs; pre-push check passes |
| 1b | Create public GitHub repo and first push | repo-keeper | repo exists, `main` pushed, no private files |
| 2 | Recording | audio-engineer | a test with a tone played through Chrome-like output plus live mic gives two non-silent, time-aligned tracks; then the user confirms with one real Messenger call |
| 3 | Transcription with per-chunk language detection, Bengali bake-off, English translation file | speech-engineer | bake-off report with measured error rates on the user's sample; English and Bengali samples transcribed; `lang` labels correct on a mixed sample; `transcript_en.md` written; GPU memory free afterwards |
| 4 | Notes, highlights, clip cutting | script-writer | `notes.md`, `highlights.json` valid, clips play and match their timestamps |
| 5 | Video brief | script-writer | `video_brief.json` validates against the schema in `prompts/llm/03_video_brief.md` |
| 6 | Optional: `watch` mode | audio-engineer | starts and stops by itself on a real call; never records outside a call |
| 7 | README, final cleanup, push | builder + repo-keeper | fresh clone + `scripts/setup.sh` works |

Model choice at stage 3 and 4 depends on the GPU found in stage 0:

- Speech: chosen by the bake-off in section 4a. Do not guess; measure.
- LLM: a multilingual instruction model in GGUF format (the single-file format llama.cpp loads) that fits the GPU with the whole transcript in context. The script-writer checks what is current, tests Bengali comprehension on a real transcript, and records the choice and the reason in a report.

### 4a. Bengali speech and translation candidates

Published accuracy numbers for Bengali come from different kinds of audio (read sentences, YouTube, competition sets) and do not agree with each other, and none were measured on phone-call audio. So the speech-engineer runs a **bake-off** (this project's own word for a side-by-side test): every candidate transcribes the same 2-3 minute sample of the user's real call audio, which the user has corrected by hand, and the one with the lowest error rate becomes the default in `config.toml`. The loser models are deleted from `models/`.

Speech-to-text candidates, in the order to try them:

| # | Candidate | Where | Why it is on the list | Watch out for |
|---|---|---|---|---|
| 1 | Bengali.AI / Tugstugi fine-tuned Whisper medium (`tugstugi_bengaliai-asr_whisper-medium`) | Hugging Face model; used in several GitHub competition repos | The usual best starting model in 2026 studies of long, conversational Bengali audio | Bengali only: use it for `bn` chunks, keep stock Whisper for `en` chunks. Convert to faster-whisper format to run it in the same engine |
| 2 | BanglaSpeech2Text, `large` model | `github.com/shhossain/BanglaSpeech2Text` (pip package with a command line) | Simplest to install; its own table claims the lowest error of its family; Apache-2.0 licence | Its numbers are on read speech; verify on call audio |
| 3 | Stock Whisper `large-v3` | via faster-whisper | Baseline; also the English model | Weak on Bengali |
| 4 | AI4Bharat IndicConformer 600M multilingual | `github.com/AI4Bharat/IndicConformerASR` | Strong on Indian languages including Bengali | Download is gated behind a Hugging Face login (needs the user); separate toolkit (NeMo); trained mostly on Indian Bengali. Optional: try only if 1-3 disappoint |
| 5 | Hishab Titu Bengali Conformer / FastConformer | Hugging Face `hishab/...` | Trained on a very large Bengali corpus | Non-commercial licence (CC BY-NC 4.0), which matters if videos made from the calls are ever monetized; did poorly in one long-form test. Optional, last |

Rules for the bake-off:

- Score with word error rate and character error rate (the share of words, or of characters, that are wrong) after the same text clean-up for every candidate. Character error rate is the fairer number for Bengali.
- Also record speed and GPU memory for each candidate.
- If a newer or better open model turns up when the agent searches, add it to the table and test it too.
- Regional dialects (Sylheti, Chittagonian and others) are much harder for every model. If the user's calls are in a dialect, say so in the report and set expectations.

Translation to English (`transcript_en.*`), candidates:

| # | Candidate | Where | Note |
|---|---|---|---|
| 1 | IndicTrans2, Indic-to-English model | `github.com/AI4Bharat/IndicTrans2` | Purpose-built translator for Indian languages incl. Bengali, MIT licence; translates sentence by sentence |
| 2 | The project's local LLM | already in the pipeline | No extra model to install; can use surrounding lines as context, which helps with the transcript's mistakes |
| 3 | Whisper's built-in speech-to-English mode | already in the pipeline | Translates straight from the audio, skipping the Bengali text; useful as a cross-check on garbled passages |

Pick by having the user judge the three outputs on the same sample. Prefer the option that adds no extra model if quality is close. Whatever wins, the Bengali original is always kept next to the English so mistakes can be traced.

---

## 5. Agents and the model stack

The main Claude Code session is the **coordinator**: it reads this file, hands out stages, checks acceptance, and talks to the user. It does not write large amounts of code itself.

| Agent | Model | Use for |
|---|---|---|
| `runner` | Haiku 5.5 | Running commands, checking tool versions, listing files, smoke tests, collecting logs |
| `builder` | Sonnet 5.5 | Routine code: CLI, config loading, file layout, tests, README, setup script |
| `repo-keeper` | Sonnet 5.5 | Git commits, privacy check, GitHub repo creation and pushes |
| `audio-engineer` | Opus 5.5, high effort | PipeWire capture, track alignment, clean start/stop, watch mode |
| `speech-engineer` | Opus 5.5, high effort | Transcription, language detection, timestamps, GPU memory handling |
| `script-writer` | Opus 5.5, high effort | Local LLM runtime, the prompts in `prompts/llm/`, notes, highlights, clips, video brief |
| `solver` | Fable 5.2, high effort | Only when the others are stuck. Diagnoses and writes a solution plan; does not execute |

### Routing rule

Give each task to the cheapest agent that can do it reliably:

1. Is it just running or checking something? -> `runner`.
2. Is it ordinary code with a clear spec? -> `builder`.
3. Is it delicate (audio routing, speech accuracy, model memory, prompt quality, anything where a subtle mistake silently ruins recordings)? -> the matching Opus agent.

### Escalation rule

- An agent that fails the same task **twice** stops and reports what it tried. The coordinator moves the task one tier up (Haiku -> Sonnet -> Opus).
- When an Opus agent fails twice, or two agents disagree, or the cause is unknown, call `solver`. The solver writes a numbered plan to `prompts/build/NN_solution_<topic>.md` with concrete steps and says which agent runs each step. The other agents then execute that plan. The solver never edits app code.
- If the solver's plan also fails, stop and ask the user. Do not loop.

Every agent obeys section 1. Every agent ends with a short report: what was asked, what it did, what the result means, problems and assumptions, and the system packages it installed (also logged in `reports/INSTALLED.md`).

If `graphify` is available on this machine, agents may run it (read-only use) to understand the code before changing it.

---

## 6. Prompts

- `prompts/build/` holds prompts for Claude agents: `01_kickoff.md` starts the build; the solver adds `NN_solution_*.md` files.
- `prompts/llm/` holds the templates the local LLM uses at run time: `01_notes.md`, `02_highlights.md`, `03_video_brief.md`. The app reads these files at run time, so they can be edited without touching code. Placeholders use `{{double_braces}}`.

---

## 7. How to report to the user

- Plain English. Define every technical word the first time it is used (software, tool and physics words alike). Do not invent terms; if a label is your own, say so.
- Order: what was asked, the concrete actions taken, what the result means, then problems and assumptions.
- Last, on every result: the "Installed on this system" list from rule 3.
- Math, if any, in LaTeX.

---

## 8. Git and GitHub

- Account: the GitHub login tied to `digonto10602@gmail.com`. Read the login name with `gh api user --jq .login`. If `gh auth status` fails, stop: the user must run `gh auth login` himself (it writes outside this folder).
- Repo: public, named `omni_recorder`, default branch `main`.
- Identity: `git config --local user.email digonto10602@gmail.com` and `git config --local user.name` set to the GitHub login.
- Before every push run `scripts/prepush_check.sh`. It must fail if any tracked or staged file:
  - is under `records/`, `models/`, `.venv/`, `.cache/`, `.tmp/`;
  - has an audio extension (`.flac .wav .mp3 .ogg .opus .m4a .webm .mkv`);
  - is a model file (`.gguf .bin .safetensors .pt`);
  - is larger than 1 MB;
  - looks like a transcript or notes from a real call (`transcript.*`, `notes.md`, `highlights.json`, `video_brief.*` outside `tests/fixtures/`).
- Test fixtures must be synthetic (generated tones, text written by the agent). Never copy real call content into `tests/`, `reports/`, prompts, commit messages or the README.
- Never force-push. Never rewrite history without asking the user.
