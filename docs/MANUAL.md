# omni-rec user manual

`omni-rec` is a local call recorder and script maker for a Linux desktop that uses PipeWire for sound
(Arch Linux with Hyprland in this project). It records Facebook Messenger calls made in Google Chrome,
and later turns them into a transcript, an English translation, notes, clips and a "video brief".

Read this in a terminal with `omni-rec manual` (press `q` to quit). A one-screen summary is
`omni-rec keys`, also on the desktop shortcut **Ctrl+Shift+Alt+H** (section 12).

Words used in this manual are explained the first time they appear. Anything marked
**planned - stage N** is not built yet: the command exists but only prints
"not implemented until stage N" and exits with code 2.

## Contents

1. What the app does
2. Privacy and consent
3. Install and setup
4. The cheat sheet
5. Commands, one by one
6. What a recording leaves behind (files in `records/<call_id>/`)
7. Capture modes and the warnings `stop` prints
8. Disk space
9. Configuration (`config.toml`)
10. Troubleshooting
11. Where the privacy check lives
12. The desktop shortcut (Ctrl+Shift+Alt+H)

## 1. What the app does

```
record  ->  transcribe  ->  notes  ->  highlights + clips  ->  video brief
```

| Step | Output in `records/<call_id>/` | Built? |
|---|---|---|
| Record | `me.flac`, `them.flac`, `mix.flac`, `meta.json` | yes |
| Transcribe (Bengali and English, language chosen per speech chunk) | `transcript.json`, `transcript.md` | planned - stage 3 |
| Translate to English | `transcript_en.json`, `transcript_en.md` | planned - stage 3 |
| Notes (local language model) | `notes.md` | planned - stage 4 |
| Highlights and clips | `highlights.json`, `clips/` | planned - stage 4 |
| Video brief (scene and frame descriptions for a video-making AI) | `video_brief.md`, `video_brief.json` | planned - stage 5 |

Plain-English definitions:

- **PipeWire** is the Linux sound server: the program that moves audio between applications, microphones
  and speakers.
- **FLAC** is a lossless audio format (smaller than WAV, nothing is thrown away). Files here are 48,000
  samples per second, 24-bit, one channel (mono).
- **Transcript** means the speech written out as text. **Highlights** are the time ranges a local language
  model picks as interesting; **clips** are those ranges cut out as separate audio files.
- **Local language model** means an AI text model that runs on this computer through `llama.cpp`
  (a program that runs such models). Nothing is sent to the internet.
- **Two separate tracks.** `me.flac` is your microphone only. `them.flac` is Chrome's sound output only
  (the other person). So every line of a transcript can be labelled "me" or "them" without any
  speaker-separation model.
- **The audio is the source of truth.** Bengali transcripts will contain mistakes; every note, highlight
  and brief item carries timestamps pointing back to the audio.

Everything runs on this machine. The app sets `HF_HUB_OFFLINE=1` (Hugging Face's "never go online"
switch) and makes no network calls. The network is used only during setup and for `git push`.

## 2. Privacy and consent

- **You are responsible for consent.** Tell the other person the call is being recorded and get their
  agreement. Laws about recording calls differ by country. You are also responsible for getting consent
  before reusing someone's words or voice in generated videos.
- `omni-rec start` prints this reminder every time:

```
REMINDER: the other person must know this call is being recorded.
You are responsible for getting their consent, both for recording the call
and for reusing their words or voice later (for example in generated videos).
```

- Recordings are private. `records/`, `models/`, `.venv/`, `.cache/` and `.tmp/` are git-ignored, and
  `scripts/prepush_check.sh` blocks audio, transcripts, notes, model files and files over 1 MB from being
  pushed (section 11). The GitHub repository is public: never copy real call content into tests, reports,
  prompts or the README.
- Models are loaded only when needed, one at a time, and nothing stays in GPU memory after a command
  finishes.

## 3. Install and setup

Requirements: Linux with PipeWire (`pw-record`, `pw-dump`, `pw-link`, `pactl`), `ffmpeg`, `uv` (a fast
Python package installer), `git`, and Google Chrome.

```
cd ~/omni_recorder
bash scripts/setup.sh        # creates .venv (Python 3.12), installs the package; downloads no models
source scripts/env.sh        # run in EVERY new shell before using omni-rec
omni-rec doctor              # should end with "0 FAIL"
```

What `scripts/env.sh` does: it is meant to be sourced (loaded into your current shell, not run as a
separate program). It points every cache, download and temporary folder inside the project, so nothing
lands elsewhere on your disk:

| variable | value |
|---|---|
| `HF_HOME` | `~/omni_recorder/models/hf` |
| `XDG_CACHE_HOME` | `~/omni_recorder/.cache` |
| `PIP_CACHE_DIR` | `~/omni_recorder/.cache/pip` |
| `TMPDIR` | `~/omni_recorder/.tmp` |
| `UV_CACHE_DIR`, `UV_PYTHON_INSTALL_DIR` | folders under `.cache/` |

It also puts `.venv/bin` first on `PATH`, which is how the shell finds `omni-rec`. The `.venv` is a
private copy of Python and the project's packages (`numpy` is the only runtime dependency so far).
`scripts/setup.sh` can be run again safely; it reuses an existing `.venv`.

If `omni-rec` is "command not found", you forgot `source scripts/env.sh`.

## 4. The cheat sheet

This text is kept in `docs/CHEATSHEET.md` and is exactly what `omni-rec keys` prints (below a one-line
status). The manual and the popup read the same file.

<!-- cheatsheet:start -->
```
omni-rec cheat sheet
------------------------------------------------------------------------
start                 Begin recording (shows the consent reminder first).
stop                  Stop; write me.flac, them.flac, mix.flac, meta.json.
status                Is a recording running? Which call, for how long.
list                  List calls and which steps are done.
process <call_id>     Transcribe + translate + notes.     [planned: stage 3-5]
    --no-translate    Skip the English translation file.
    --highlights      Also pick and cut the interesting parts.
    --brief           Also write the video brief.
    --all             Everything.
doctor                Check tools; clean up after a crash; recover audio.
watch                 Auto start/stop on a Chrome call.   [planned: stage 6]
manual                Read the full manual (q quits).
keys, cheatsheet      Show this sheet.
--help, --version     Built-in help; version number.
------------------------------------------------------------------------
Tell the other person the call is being recorded. Wear headphones.
```
<!-- cheatsheet:end -->

## 5. Commands, one by one

Every command is `omni-rec <command> [options]`. `omni-rec --help` lists them; `omni-rec <command> --help`
shows one command's options. **Exit code** means the number a command leaves behind for scripts: 0 is
success, anything else is a problem.

### `omni-rec start` - begin recording

Prints the consent reminder (section 2) first, then starts a background helper (the "supervisor") that
keeps recording after you close the terminal. Example output:

```
Recording call 2026-11-17_1458
  folder:      /home/<you>/omni_recorder/records/2026-11-17_1458
  microphone:  <name of your default microphone>
  Chrome:      no playback stream yet; it is linked automatically as soon as Chrome plays sound
  fallback:    <your output device> monitor (used only if Chrome is never found)
Stop with: omni-rec stop
```

- `<call_id>` is the date and start minute, `YYYY-MM-DD_HHMM`; `_2`, `_3` are added if two calls start in
  the same minute.
- Start it before or just after you begin the call. If Chrome is not making sound yet, the line says so and
  Chrome is picked up automatically within about 0.3 s of its sound starting.
- Refuses to start (exit code 1) if a recording is already running, if a required tool is missing, or if
  fewer than 5 GB are free (section 8).
- Nothing is changed permanently in PipeWire. The recorder adds one temporary recording node and a few
  connections; they vanish when recording stops, even after a crash. Chrome keeps playing to your speakers
  or headphones exactly as before.

### `omni-rec stop` - stop and finalize

Stops the helper, then converts the raw capture into the finished files. A one-hour call takes a short
while to convert. Example output:

```
Stopped. Call 2026-11-17_1458: 1805.2 s, mode: chrome-only
  .../records/2026-11-17_1458/me.flac  (1805.20 s, RMS -38.1 dBFS, active 42.0 %)
  .../records/2026-11-17_1458/them.flac  (1805.20 s, RMS -33.5 dBFS, active 55.3 %)
  .../records/2026-11-17_1458/mix.flac  (1805.20 s, ...)
  .../records/2026-11-17_1458/meta.json
```

(The numbers are examples.) **dBFS** is decibels relative to the loudest value a file can hold; 0 is the
maximum, and quieter sound is more negative. **RMS** is the average loudness. **Active** is the share of the
recording that contained sound (measured in 100 ms windows louder than -45 dBFS). If anything looks wrong a
red-flag block of warnings follows (section 7). Exit code 1 and "no recording is running" if there is nothing to
stop.

### `omni-rec status` - is a recording running?

- Idle: `Not recording.` (exit code 0)
- Running: the call id, minutes and seconds recorded, the capture mode right now, the microphone, each Chrome
  stream found, and the fallback device. A `last error:` line appears only if the helper hit a problem.
- Interrupted (crash or reboot): `NOT running, but call ... was interrupted`, exit code 3. Run
  `omni-rec doctor`.

### `omni-rec list` - which steps are done

Prints one row per call in `records/`, with `yes` or `-` for each step: `record`, `transcribe`,
`translate`, `notes`, `highlights`, `brief`. A step counts as done when its output files exist. If there are
no calls it says so.

```
call_id              record     transcribe translate   notes      highlights brief
2026-11-17_1458      yes        -          -           -          -          -
```

### `omni-rec process <call_id>` - planned - stage 3-5

Planned as in the project plan: transcribe, translate to English and write notes for one call.
Today it prints `omni-rec process: not implemented until stage 3.` and exits with code 2.
Options (also not active yet):

| option | meaning |
|---|---|
| `--no-translate` | skip the English translation file |
| `--highlights` | also pick and cut the interesting parts |
| `--brief` | also write the video brief |
| `--all` | everything |

Example (planned): `omni-rec process 2026-11-17_1458 --all`. Use `omni-rec list` to see call ids.

### `omni-rec doctor` - check and clean up

Checks that the tools exist (`ffmpeg`, `ffprobe`, `pw-record`, `pw-dump`, `pw-link`, `pactl`, `wpctl`,
`git`, `gh`, `nvidia-smi`), the graphics card and its free memory, Chrome, the Python in `.venv`,
`config.toml`, the environment variables and the models folder. Each line starts with `OK`, `WARN` or
`FAIL`; the last line is a count such as `16 OK, 0 WARN, 0 FAIL`. Exit code 1 only if something FAILs.

It also **cleans up leftovers**, and this is the recovery tool after a crash:

- stops helper processes and removes recorder objects left behind by a recording that died;
- converts every unfinished capture in `records/` into FLAC files and `meta.json`, with
  `"recovered_after_crash": true` in `meta.json`;
- it never touches a recording that is running, and never touches anything not named `omni_rec_`.

It is safe to run at any time.

### `omni-rec watch` - planned - stage 6

Optional automatic start and stop when a Chrome call is detected. Today it prints
`omni-rec watch: not implemented until stage 6.` and exits with code 2.

### `omni-rec manual`

Shows this manual. In a terminal it opens in `less -R` (a pager: Space = next page, `b` = back, `/word` =
search, `q` = quit). When the output goes to a file or pipe, it is printed plainly, so
`omni-rec manual | head` works.

### `omni-rec keys` (alias `omni-rec cheatsheet`)

Prints one status line - `Status: not recording`, or `Status: RECORDING call <id> for <m> min <s> s`, or a
note that a call was interrupted - followed by the cheat sheet of section 4. Used by the desktop shortcut.

## 6. What a recording leaves behind

Each call lives in `records/<call_id>/` (private, never committed):

| file | what it is |
|---|---|
| `me.flac` | your microphone only (mono, 48 kHz, 24-bit) |
| `them.flac` | the other person: Chrome's sound only, or all system sound in fallback mode (section 7) |
| `mix.flac` | both together, mono. A constant gain (a fixed volume factor) is applied only to stop it clipping; no compression or other processing |
| `them_system.flac` | only written when Chrome's channels were silent but the computer did play sound (the "CHROME SILENT" warning): a copy of all system sound to check |
| `meta.json` | facts about the recording (below) |
| `ffmpeg_finalize.log` | only present if conversion printed something |
| `capture_000.f32` ... | the raw capture. Deleted after a successful stop unless `keep_raw_capture = true` |
| `capture.json`, `events.jsonl` | live bookkeeping written during recording (setup, events) |
| later stages | `transcript.*`, `transcript_en.*`, `notes.md`, `highlights.json`, `clips/`, `video_brief.*` |

All three main files have exactly the same length and start at the same instant. They are channels of one
capture, so sample number *i* of `me.flac` and of `them.flac` was recorded in the same moment, and they cannot
drift apart.

**`meta.json`** is plain JSON (a text format for structured data). Its main entries:

| key | meaning |
|---|---|
| `call_id`, `app_version`, `schema` | identity and format version |
| `start_wall`, `end_wall` | start and end clock time with timezone; `start_time_uncertainty_s` is how precisely the start is known (a few milliseconds) |
| `duration_s`, `sample_rate` | length in seconds; 48000 |
| `files` | per file: sample count, duration, and `stats` (`rms_dbfs`, `peak_dbfs`, `active_fraction`, `active_span_s`, `clipped_samples`); `mix.flac` also lists `gain_applied` |
| `them_mode` | `chrome-only` or `fallback-system-monitor` (section 7) |
| `them_mode_reason` | why that mode was chosen |
| `capture` | how it was captured: recorder node name, channel layout, microphone(s) used, every Chrome stream seen (with its `media.name`), seconds Chrome was linked (`chrome_linked_s`), monitor device used, statistics of all tracks |
| `alignment` | proof of alignment: shared clock, start offset 0 ms, `length_difference_ms` (0 expected) |
| `segments` | recording pieces; more than one if the recorder was restarted, with any silence inserted to keep real time |
| `bleed_check` | result of the speaker-bleed test (section 7) |
| `warnings` | the list of warnings `stop` printed; empty means nothing was flagged |
| `events` | notable events with their position in seconds (a stream appearing, a restart, ...) |
| `tools` | program versions used |
| `recovered_after_crash` | true if `doctor` rebuilt this call after a crash |

## 7. Capture modes and the warnings `stop` prints

**Chrome-only mode** (`"them_mode": "chrome-only"`, normal). The recorder finds Chrome's sound stream by
the program name that PipeWire reports for it (`chrome`, or `chromium`), and records that stream only. Steam's
built-in browser, which calls itself "Chromium" on this machine, is excluded by name. Any
Chrome tab that plays sound is included: a YouTube tab playing during the call would be in `them.flac` too.
`meta.json` lists every stream with its name so you can see.

**Fallback mode** (`"them_mode": "fallback-system-monitor"`). If no Chrome stream was ever found during the
recording, `them.flac` is built from the **monitor** (a read-only copy) of your default output device, i.e.
all system sound. This is always recorded in parallel as a safety net, and `meta.json` says which mode was used.
It can be turned off with `fallback_to_default_monitor = false` in `config.toml`.

Warnings are printed by `stop` between lines of `!!!` and saved in `meta.json` under `warnings`. They are
alerts, not failures: the files are still written.

| warning begins | what it means | what to do |
|---|---|---|
| `FALLBACK:` | Chrome's own stream was never found; `them.flac` holds all computer sound (notifications, music, other tabs) | Check Chrome was really playing the call (not another browser). Check `meta.json` > `capture.chrome_streams`; add the program name to `chrome_binaries` in `config.toml` if it is a different browser. Mute other sounds next time |
| `CHROME SILENT:` | Chrome's stream was linked but carried no sound, though the computer played some | Listen to `them_system.flac` (all system sound). The call may have been played through another app or tab |
| `CHROME ABSENT:` | No Chrome stream was linked for a long part of the call (more than 10 s and more than 10 % of it), for example before the call connected, or while it reconnected | Normal for a late start. If sound is missing from `them.flac`, start recording before the call connects next time |
| `SILENT:` | one track has sound in less than 0.5 % of the recording | `me.flac` silent: wrong or muted microphone (section 10). `them.flac` silent: Chrome was muted, or the call had no sound |
| `CLIPPED:` | the track hit the maximum level 100 or more times, so it is distorted there | Lower the microphone gain or call volume. The distortion cannot be repaired afterwards |
| `SHORT:` | for a call of 30 s or more, one track's sound spans under half the time of the other's | Part of one side may be missing: check the microphone was on the whole time |
| `BLEED:` | your microphone picks up the other side's voice from your speakers, with a delay (shown in ms) | Wear headphones. Bleed makes "me" and "them" harder to tell apart and can cause duplicate lines in the transcript |
| `EVENT capture_process_died ...` / `link_failed` / `mic_missing` / `daemon_error` | something went wrong while recording, at the position shown | If `capture_process_died`, the recorder restarted by itself and silence was inserted for the gap; the rest is intact. `mic_missing`: your microphone was unplugged or not found |

The bleed test works on a 8 kHz copy of both tracks: for each 2 s block where `them` is clearly audible it checks
whether `me` contains a delayed copy. Its thresholds were tuned on synthetic sound only, so on real calls it may
need adjusting.

## 8. Disk space

While recording, the capture is raw: 6 channels of 32-bit numbers at 48,000 per second, about
**4.1 GB per hour**. When you run `stop` it is converted to the much smaller FLAC files and the raw file is
deleted. `start` refuses to run with **less than 5 GB free** on the disk holding `records/`. A long call therefore
needs room for the raw file plus the FLAC files while converting. `doctor` and `stop` do the conversion with a
streaming method, so memory use does not grow with call length.

## 9. Configuration (`config.toml`)

Relative paths are relative to the project folder. Set `OMNI_CONFIG=/path/to/other.toml` to use a different file.
No model name or device name is hard-coded in the program; they live here.

**[paths]**

| key | meaning |
|---|---|
| `records_dir` | where calls are stored (`records`) |
| `models_dir` | where downloaded models live (`models`) |
| `runtime_dir` | state of a running recording (`.tmp/recorder`) |

**[audio]**

| key | meaning |
|---|---|
| `sample_rate` | 48000 |
| `chrome_binaries` | program names counted as Chrome (`["chrome", "chromium"]`); compared exactly, ignoring case |
| `chrome_stream_match` | fallback match on the stream's display name, used only for streams that report no program name |
| `exclude_binaries` | programs never treated as Chrome (`["steamwebhelper"]`) |
| `fallback_to_default_monitor` | also record all system sound as a safety net (`true`) |
| `mic_source` | `"default"` follows the system default microphone, even if it changes during the call |
| `output_monitor` | `"default"` follows the default output device |
| `poll_interval_s` | how often the recorder re-reads the audio graph to link new Chrome streams (0.3) |
| `keep_raw_capture` | keep the raw 32-bit capture after `stop` (about 4 GB per hour; `false`) |

**[languages]** `allowed = ["bn", "en"]` (Bengali and English; the language is detected per speech chunk).

**[speech]**, **[translation]**, **[llm]** hold the speech model names, the translation method, the language-model
file and its settings (`gguf_path`, `context_length`, `n_gpu_layers`, `prompts_dir`). Several are blank on purpose
until the stage 3 and 4 tests choose the winners (planned - stage 3-4).

## 10. Troubleshooting

**First step for almost anything: `omni-rec doctor`.** It reports what is missing and cleans up leftovers.

- **"omni-rec: command not found"** - run `source scripts/env.sh` in this shell. If `.venv` does not exist yet,
  run `bash scripts/setup.sh`.
- **Crash, reboot or power cut while recording** - `omni-rec status` shows `NOT running, but call ... was
  interrupted`. Run `omni-rec doctor`: it cleans up and converts the captured audio into FLAC files. Everything
  recorded up to the crash is kept. If the audio server only restarted, the recorder carries on by itself and
  fills the gap with silence so later sound keeps its real time position.
- **`stop` says "no recording is running"** - nothing was recording. If you think it was, run
  `omni-rec doctor`, then `omni-rec list` and look for a call with `record yes`.
- **"already recording call ..." on start** - run `omni-rec stop` first.
- **"only N GB free"** - free disk space (section 8).
- **No Chrome stream found** (`start` says "no playback stream yet", or `stop` printed `FALLBACK:`). Chrome only
  has a sound stream while it is playing sound, so this is normal before the call connects. If it stays so:
  check that the call is in Google Chrome (not another browser or Steam's browser), that the tab is not muted,
  then run `omni-rec status` during the call to see the Chrome stream. A different browser's program name can be
  added to `chrome_binaries`. Until Chrome is found, all system sound is recorded in parallel as the fallback.
- **Wrong or silent microphone** (`me.flac` flagged `SILENT`, or `start` printed "NOT FOUND"). `me` is always the
  **system default microphone**, which is not necessarily the one Messenger uses. Set the default input in the
  desktop sound settings (for example with `wpctl status` to see devices and `wpctl set-default <id>`), check it is
  not muted, then record a short test. Unplugging the microphone mid-call is reported as `mic_missing`.
- **Bleed / echo** (`BLEED:` warning, or "them" heard inside `me.flac`) - wear headphones. This is the only real
  fix; speakers and a microphone in the same room always leak.
- **Part of the call missing from `them.flac`** - `CHROME ABSENT` or `SHORT` warning; start recording earlier next
  time. Sound from the time no Chrome stream was linked is not kept in `them.flac`.
- **Process commands say "not implemented"** - expected; see the "planned" markers above.
- **GPU memory is occupied** - nothing the app does keeps a model in GPU memory after a command ends. Check
  `nvidia-smi`; `doctor` shows free memory.

## 11. Where the privacy check lives

`scripts/prepush_check.sh` is the gate you must run before every `git push`:

```
bash scripts/prepush_check.sh
```

It exits with an error and lists the files if any tracked or staged file is under `records/`, `models/`, `.venv/`,
`.cache/`, `.tmp/`; has an audio or video extension; is a model file (`.gguf`, `.bin`, `.safetensors`, `.pt`,
`.onnx`); is larger than 1 MB; or looks like a real call's transcript, notes, highlights or video brief
(allowed only under `tests/fixtures/`). Tests that prove it rejects a fake audio file and a fake `records/` file
are in `tests/test_prepush_check.py`. Test data in this project is always synthetic (generated tones and made-up
text).

## 12. The desktop shortcut (Ctrl+Shift+Alt+H)

Pressing **Ctrl+Shift+Alt+H** (hold Ctrl, Shift and Alt, then tap H) opens a floating, see-through terminal window
showing the cheat sheet and whether a recording is running. Press any key (q, Esc, Enter...) to close it.

How it works, so you can undo it. The binding is one line in Hyprland's key-binding file
`~/.config/hypr/bindings.lua`. This is the only change this project makes outside its own folder, and you
approved it. The line runs `omarchy-launch-tui --app-id=TUI.float bash ~/omni_recorder/scripts/show_keys.sh`:
Omarchy's own launcher for a terminal program, using the window class `TUI.float` that Omarchy already floats,
centers and makes semi-transparent. `scripts/show_keys.sh` loads `scripts/env.sh`, runs `omni-rec keys` and
waits for a key. To remove the shortcut, delete the line marked `omni-rec cheat sheet` in `bindings.lua` (a backup
of the file from before the change sits beside it as `bindings.lua.bak.<number>`; `reports/05_manual.md` names it),
then run `hyprctl reload`. The other shortcut on Ctrl+Shift+Alt, `R`, belongs to a different tool (reminders) and
is untouched.

You can also run the same screen in any terminal: `bash scripts/show_keys.sh`, or just `omni-rec keys`.
