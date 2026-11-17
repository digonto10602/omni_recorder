# Stage 2 report: recording (`omni-rec start / stop / status`, doctor cleanup)

- Date: 2026-11-17
- Git commit: e3c73a9 (base; this stage's changes are not committed yet, repo-keeper commits them)
- Prompt in force: Stage 2 task from the coordinator (CLAUDE.md section 4, stage 2 row; section 1 rules 5 and 8)
- Related reports: `reports/01_audit.md`, `reports/02_skeleton.md`, `reports/03_repo.md`
- Author: audio-engineer agent

Terms used below, defined once:
**PipeWire** is the Linux sound server. **WirePlumber** is the program that decides which audio things get connected.
A **node** is one audio object (a microphone, a speaker output, a browser's playback stream). A **port** is one channel
input or output of a node. A **link** connects an output port to an input port. A **sink** is an output device. A
**monitor** is a read-only copy of what a sink is playing. A **driver** is the device whose clock paces a group of
linked nodes. **dBFS** means decibels relative to the loudest value a file can hold (0 dBFS). **RMS** is the average
signal power. **FLAC** is a lossless audio format. A **daemon** (here: the "supervisor") is a background process
that keeps running after the command that started it has exited. A **PID file / state file** is a small file holding
process numbers so later commands can find them. **ppm** means parts per million.

## 1. What was asked

Build `omni-rec start / stop / status` and the `doctor` cleanup so that every call produces `me.flac` (microphone
only), `them.flac` (Chrome's sound only when possible, else all system sound, and say which), `mix.flac`, and
`meta.json`. Requirements: no persistent audio changes; both tracks share one start time (target under 50 ms drift
over 30 min, offset and length within 20 ms); clean stop and crash tolerance; survive Chrome streams that appear late,
vanish and come back; warnings for silent, clipped or short tracks and for speaker bleed; keep the consent reminder;
synthetic tests and a live acceptance test; do not change what the user hears.

## 2. Evidence gathered on this machine before choosing the design

| finding | evidence (command) |
|---|---|
| The client called **"Chromium input" is Steam's built-in browser**, not the Chromium browser: process binary `steamwebhelper`, command line with `--user-agent-product=Valve Steam Client`. The audit's "Chromium 155 is running with audio streams" was this. Matching streams by the name "Chromium" would record Steam sounds. | `pw-dump \| jq '... application.name ...'`, `ps -o args -p 559808` |
| Google Chrome's audio client reports `application.process.binary = "chrome"` (pid 7044, `/opt/google/chrome/chrome --utility-sub-type=audio.mojom.AudioService`). | same |
| `pw-record --target <serial of a playback stream>` works here: WirePlumber links the stream's `output_FL/FR` straight into the recorder, and the level is exact (source file mean -36.1 dB, captured -36.2 dB). So "record Chrome's stream node directly" is possible. | `pw-play ... tone1k.wav` + `pw-record --target 575 ...`, `pw-link -l`, `ffmpeg -af volumedetect` |
| A capture node with **no links does not run** (0 bytes in 3 s). With `node.always-process = true` it runs in real time on PipeWire's internal "Dummy-Driver" (47,616 frames/s over a 2 s timeout, i.e. 48 kHz minus start-up). | `pw-record --target 0 ...` file sizes |
| In raw mode `pw-record --format s24` writes **4 bytes per sample** (same size as s32), so its bit alignment is ambiguous; `f32` (32-bit float) is unambiguous and cannot clip during capture. | sizes of 2 s mono captures: s16 190,464 B, s24/s32/f32 380,928 B |
| Clock rates measured for 600 s against the system clock: onboard output (monitor) 47,999.41 Hz = **-12.30 ppm**; Blue Snowball mic 47,999.42 Hz = **-12.11 ppm**; difference 0.19 ppm (about 0.34 ms per 30 min). Method: two independent `pw-record` processes, bytes counted every second (no audio stored), least-squares slope over 595 points, worst residual 31 frames (0.65 ms). The near-identical rates are probably because both devices derive their clock from the same chipset crystal; that is my guess and was not verified. Other microphones (Bluetooth, other USB devices) can differ by tens of ppm, so the design must not rely on this. | scratch script `clockrate.py`, result `.tmp/exp/clockrate.json` |
| `pw-dump` costs about 13 ms wall time and 10 ms CPU per call, so re-reading the graph every 0.3 s costs about 3 % of one CPU core. | timing loop over 10 calls |

## 3. Design (and why)

**One recorder node with six channels, linked by a small supervisor.**

- `omni-rec start` starts a supervisor (`python -m omni_recorder.capture_daemon`, in its own session so it survives
  the terminal). The supervisor starts **one** `pw-record` process that creates the node
  `omni_rec_capture_<call_id>` with `node.autoconnect = false` (WirePlumber never connects it by itself) and writes
  raw 32-bit float audio to `records/<call_id>/capture_000.f32`.
- Channel layout: **0-1 = microphone**, **2-3 = every Chrome/Chromium playback stream** (PipeWire adds up streams
  linked into the same port), **4-5 = monitor of the default output** (all system sound, the fallback).
- Every 0.3 s the supervisor reads `pw-dump` and makes the links **into its own node** match what is wanted:
  new Chrome streams are linked, links to vanished nodes disappear by themselves, a changed default microphone or
  default output is re-linked. It never creates or removes any other link, and never moves Chrome's stream, so
  Chrome keeps playing to the speakers or headphones exactly as before (an output port can feed several links).
- Chrome streams are matched by **program name** (`application.process.binary` exactly `chrome` or `chromium`,
  read from the node or, if missing there, from its client). Excluded: `steamwebhelper`, input streams, our own node.
  The name substring match (`"Google Chrome"`) is used only for a stream that reports no program at all.

Why this instead of one `pw-record --target <Chrome node>` per stream:

1. **Alignment by construction.** `me` and `them` are channels of one node, so sample *i* of `me.flac` and sample
   *i* of `them.flac` were captured in the same audio cycle. There is nothing to trim or pad, and they cannot drift
   apart whatever microphone is used. Two separate `pw-record` processes would each count samples on their own
   device's clock (section 2) and would need drift correction.
2. **Stream churn without timeline breaks.** Chrome's stream can appear after start, vanish and come back with a new
   number; the recorder keeps running (it is always linked to the mic and the monitor), so the timeline continues
   and silence is recorded where Chrome had no stream. With `--target`, a vanished target ends or re-routes that
   recorder, and a new one would start a new file.
3. **Never silently records the wrong thing.** With `--target`, WirePlumber may re-link a recorder whose target
   disappeared to the *default source*, i.e. the microphone would end up in `them`. Here nothing is auto-linked.
4. **Built-in fallback.** The monitor channels are always recorded. At stop, `them.flac` comes from the Chrome
   channels if any Chrome stream was linked during the call; otherwise from the monitor, and `meta.json` says
   `"them_mode": "fallback-system-monitor"` with a loud warning. If Chrome was linked but its channels are silent
   while the system played sound, `them_system.flac` is also written and a warning says so.

**Runtime objects and cleanup (rule 5).** The only PipeWire objects created are the recorder node and links into
it. All belong to the `pw-record` process: when it exits (normally or killed), PipeWire removes them. No config file
is written, nothing is "lingering". `pw-record` gets a parent-death signal (Linux `prctl(PR_SET_PDEATHSIG, SIGINT)`),
so if the supervisor dies, the recorder stops cleanly too: there is never an unsupervised recording.

**Crash tolerance.** The raw file has no header; every whole frame written is valid audio. `capture.json` (format,
layout, segment start times) and `events.jsonl` (one line per event, flushed and fsync'ed) are written while
recording. If `pw-record` dies while the supervisor lives (e.g. PipeWire restart), a new segment `capture_001.f32`
starts and the gap is filled with silence at stop, so later audio keeps its real time position.

**Stop.** `omni-rec stop` sends SIGTERM to the supervisor; the supervisor sends SIGINT to `pw-record` (it flushes
and closes the file), logs the final position and exits. Then `stop` waits until the node has left the graph,
converts in two streaming passes (statistics, then encoding; memory use does not grow with call length), verifies
each FLAC's sample count with `ffprobe`, renames `*.part` files into place, writes `meta.json` and only then deletes
the raw capture (config `keep_raw_capture = false`).

**Output formats.**
- `me.flac`: mono, (ch0 + ch1) / 2. A mono microphone port is linked to both channels, so the level is unchanged.
- `them.flac`: mono, (L + R) / 2. Messenger call audio is a mono voice; mono halves nothing useful and matches what
  speech recognition needs. (The raw stereo is kept if `keep_raw_capture = true`.)
- `mix.flac`: mono, (me + them) x gain, where the constant gain is at most 1 and only lowers the level so the peak
  stays at or below -1 dBFS (no dynamic processing). Mono is easiest to listen to; the separate tracks keep the
  speaker separation.
- All 48 kHz, 24-bit FLAC (lossless relative to 24 bits; the float capture is converted once).

**Checks at stop** (all in `meta.json` "warnings", printed between `!!!` lines):
- SILENT: sound (100 ms windows above -45 dBFS RMS) in fewer than 0.5 % of windows.
- CLIPPED: at least 100 frames at full scale (|x| >= 0.999).
- SHORT: one track's active span (first to last sound) under 50 % of the other's, calls of at least 30 s.
- CHROME ABSENT: no Chrome stream linked for more than 10 s and more than 10 % of the call.
- FALLBACK / CHROME SILENT: see above.
- BLEED: the other side's voice is heard by the microphone (speaker leakage). Both tracks are reduced to 8 kHz; for
  each 2 s block where `them` is above -40 dBFS the normalized cross-correlation with `me` is computed for delays
  -50 ms to +500 ms. Bleed is reported when at least 30 % of judged blocks peak above 0.2 and at least half of those
  peaks agree on the delay within 3 ms. The warning says headphones give cleaner separation. These thresholds were
  set on synthetic signals only (see problems).
- Events that indicate trouble (`capture_process_died`, `link_failed`, `mic_missing`, `daemon_error`).

**State.** `.tmp/recorder/` (config `[paths] runtime_dir`): `state.json` (call, supervisor PID, its kernel start
time and the boot id, so a PID reused after a reboot is never mistaken for ours), `live.json` (what is linked now,
rewritten every poll), `lock` (file lock so two commands never start/stop at once).

**Doctor.** `cleanup_leftovers()` now: leaves a live recording alone; for a stale state (supervisor gone) stops any
remaining recorder of that call and clears the state; stops orphan supervisors of this runtime dir and any
`pw-record` capture process whose parent is not a live supervisor; stops `pw-play/pw-cat/pw-loopback` helpers whose
command line names an `omni_rec_` object **only if they are orphaned** (parent gone, adopted by PID 1 or `systemd`;
helpers of a still-running program are reported and left alone); destroys any lingering `omni_rec_` node (none are
ever created); then converts every unfinished capture in `records/` to FLAC + `meta.json` with
`"recovered_after_crash": true`. Nothing not named `omni_rec_` is touched.

## 4. Files changed

| file | change |
|---|---|
| `src/omni_recorder/pwgraph.py` | new: parse `pw-dump`, Chrome matching, default devices, left/right port pairing, wanted-links set, `pw-link` wrappers |
| `src/omni_recorder/capture_daemon.py` | new: the supervisor (starts `pw-record`, links, events, restarts, clean shutdown) |
| `src/omni_recorder/finalize.py` | new: raw -> FLAC, timeline with gaps, statistics, warnings, `meta.json` |
| `src/omni_recorder/audiocheck.py` | new: streaming statistics, sanity warnings, bleed detector |
| `src/omni_recorder/recorder.py` | stub replaced: start / stop / status, state file, process safety checks, cleanup |
| `src/omni_recorder/cli.py` | `start` (consent reminder first, unchanged text), `stop`, `status` wired |
| `src/omni_recorder/doctor.py` | `cleanup_leftovers()` implemented (one line per action) |
| `config.toml` | `[audio]`: `chrome_binaries`, `exclude_binaries`, `output_monitor`, `poll_interval_s`, `keep_raw_capture`; `chrome_stream_match` now `["Google Chrome"]` (name fallback only); `[paths] runtime_dir` |
| `pyproject.toml` | runtime dependency `numpy>=2.0` |
| `tests/fixtures/pw_dump_synthetic.json` | new, hand-written synthetic graph |
| `tests/test_pwgraph.py`, `tests/test_finalize.py`, `tests/test_recorder_state.py` | new unit tests |
| `tests/test_live_recording.py` | new live acceptance tests (skipped unless `OMNI_LIVE_AUDIO=1`) |
| `tests/test_cli.py` | start/stop/status tests updated (no real recording in unit tests) |

## 5. Acceptance measurements

All live numbers come from `source scripts/env.sh && OMNI_LIVE_AUDIO=1 pytest -q -s tests/test_live_recording.py`,
measurements saved by the test to `.tmp/live_test/results.json`. Final run after the last code change:
`-k "not long"` **6 passed in 73.6 s**; the 30-minute test (`OMNI_LIVE_LONG_S=1800`) passed separately.

**Test rig (nothing audible, real microphone not used).** One `pw-play` process plays a stereo file: left = 1 kHz
tone at 0.1 (-20 dBFS) for "them", right = 440 Hz at 0.1 for "me", plus 10 ms bursts at 0.8 at the same sample on
both channels. Two identical `pw-loopback` relays split the channels: one relay's output node poses as Chrome
(`application.process.binary = omni_rec_test_chrome`, added to the test config's match list) and plays into a test
sink `omni_rec_test_sink`; the other relay's output is the test config's microphone. The test sink is a
`pw-loopback` whose output goes nowhere. Every test object belongs to a test process and vanishes with it.

### 5.1 Separation, levels, alignment (`test_live_record_separation_alignment_cleanup`, 13.33 s call)

| quantity | me.flac | them.flac | how |
|---|---|---|---|
| mean / max volume | -22.5 / -1.9 dB | -22.5 / -1.9 dB | `ffmpeg -af volumedetect` |
| own tone level | 440 Hz: -20.00 dBFS | 1 kHz: -20.00 dBFS | Hann-window FFT on the burst-free part 2.477-4.077 s |
| other side's tone | 1 kHz: -167.0 dBFS | 440 Hz: -236.1 dBFS | same; i.e. separation > 140 dB (numerically zero leakage) |
| burst onsets found | 5 | 5 | first sample with abs value > 0.4 after 0.5 s quiet |
| onset offset me - them | raw +0.104 ms every burst; minus the detector's known bias 0.106 ms = **-0.002 ms** (limit 20 ms) | | bias = asin(0.5)/(2 pi) x (1/440 - 1/1000) s |
| samples | 640,000 | 640,000 | **length difference 0.0 ms** (limit 20 ms) |
| mix.flac | mean -24.5 dB, max -1.0 dB (gain limited the peak to -1 dBFS) | | volumedetect |
| format | FLAC 48,000 Hz, mono, 24-bit | same | `ffprobe -show_entries stream=...` |
| start time | 2026-11-17T14:58:09.970-05:00, uncertainty 5.1 ms | same instant | `meta.json` start_wall, start_time_uncertainty_s |

Separation first measured 52 dB over the whole file; the cause was the test signal (a 10 ms burst with hard edges
spreads energy over all frequencies, including 440 Hz), not the recorder: on burst-free audio the leftover after
removing the 1 kHz tone is -144 dBFS, the 24-bit rounding floor. The test now measures on burst-free audio.

### 5.2 Chrome stream churn (`test_live_chrome_churn`)

Recording started with **no** Chrome stream; the Chrome-like stream appeared 2 s later, played, was destroyed,
and a new one (new serial) appeared 2 s later and played. Events in `meta.json` (position in the recording):
`mic_linked` 0.043 s, `monitor_linked` 0.043 s, `chrome_stream_linked` 2.325 s (serial 985),
`chrome_stream_gone` 6.229 s, `chrome_stream_linked` 8.512 s (serial 1031), `capture_stopped` 12.843 s.
One recorder process throughout (1 segment), 4 bursts in each track, onset offset -0.002 ms, length difference
0.0 ms, duration 12.84 s for 13.49 s of wall time including CLI start/stop. The link appears up to one poll
interval (0.3 s) after the stream; that short start is still in the monitor channels.

### 5.3 Fallback (`test_live_fallback_monitor`)

Same rig, match list without the test program: `them_mode = "fallback-system-monitor"`, warning "FALLBACK: Chrome's
own audio stream was never found, so them.flac holds ALL sound the computer played ..." printed by `stop`;
them.flac 1 kHz at -20.00 dBFS, 440 Hz at -236.1 dBFS; onset offset -0.002 ms.

### 5.4 Cleanup after stop

After every test: no node whose name starts with `omni_rec_` in `pw-dump`, no supervisor or capture `pw-record`
process (checked in the test fixture's teardown, all 5 tests). In 5.1 explicitly:
`leftover_nodes_after_stop = []`, `leftover_procs_after_stop = []`.

### 5.5 Crash recovery (`test_live_crash_recovery`, two variants)

| step | supervisor killed with SIGKILL | supervisor and pw-record both SIGKILL ("power cut") |
|---|---|---|
| processes 1.5 s later | none (pw-record stopped itself via parent-death signal) | none |
| `omni_rec_capture_` nodes | none | none |
| `omni-rec status` | exit 3: "NOT running, but call ... was interrupted ... Run `omni-rec doctor`" | same |
| `omni-rec doctor` | "stale state ... cleaning up", "recovered 2026-11-17_1458: 4.2 s written to FLAC" | same |
| recovered files | me/them mean -22.1 dB, `recovered_after_crash: true`, raw deleted, state cleared | same |
| fresh start/stop after | works (`2026-11-17_1458_2`, meta.json written) | works |

Final run: doctor reports the test's own relays as "still has a live parent ... left alone" and stops only the
stale recorder. Separately, a deliberately orphaned `pw-loopback -n omni_rec_test_orphan` (adopted by `systemd`,
pid 1611) was stopped by `omni-rec doctor` ("leftover pw-loopback ... stopped with SIGINT"), after which `pw-dump`
listed 0 nodes named `omni_rec_`.

### 5.6 Long run: drift over 30 minutes (`test_live_long_drift`, `OMNI_LIVE_LONG_S=1800`)

Command: `source scripts/env.sh && OMNI_LIVE_AUDIO=1 OMNI_LIVE_LONG_S=1800 pytest -q -s tests/test_live_recording.py -k long_drift`
(1 passed in 1820 s). The player was restarted 179 times (10 s file, 2 bursts each) while one recording ran.

| quantity | value |
|---|---|
| recording length | 1802.60 s for 1803.5 s wall time between `start` returning and `stop` |
| bursts found | 358 in me.flac, 358 in them.flac |
| onset offset, first burst / last burst | -0.002 ms / -0.002 ms (bias-corrected; raw 0.104 ms) |
| **drift over 30 min** | **0.000 ms** (target under 50 ms); worst single offset 0.002 ms (limit 20 ms) |
| length difference | 0 samples (86,524,928 each) |
| separation (burst-free part) | them: 1 kHz -20.00 dBFS, 440 Hz -263.6 dBFS; me: 440 Hz -20.00 dBFS, 1 kHz -167.0 dBFS |
| supervisor CPU / memory | 67.9 s CPU over 1803 s = 3.8 % of one core; 43 MB resident |
| pw-record CPU / memory | 2.8 s CPU; 10 MB resident |
| `omni-rec stop` incl. conversion | 14.0 s for 30 min of audio |
| FLAC sizes (synthetic tones) | me 86.8 MB, them 94.0 MB, mix 90.5 MB (speech will differ) |

What this proves and what it does not: it proves that within the single capture node no channel ever gains or loses
a buffer against another over 30 minutes, which is the property the alignment rests on. The rig is all virtual, so
it does not exercise two real hardware clocks; that case is covered by design (one node, one clock; PipeWire
resamples the second device) and by the clock measurement in section 2 (0.19 ppm between the two real devices, i.e.
0.34 ms per 30 min even for separate recorders).

### 5.7 Recorder restart keeps the timeline (`test_live_recorder_restart_keeps_timeline`)

`pw-record` was killed with SIGKILL 4.43 s after start while the supervisor kept running (this simulates the audio
server restarting). The supervisor logged `capture_process_died` (exit -9) at 4.139 s of audio, started segment
`capture_001.f32` about 1 s later and re-linked mic, monitor and Chrome. At stop the timeline was rebuilt:

| segment | offset (frames) | frames | silence inserted before |
|---|---|---|---|
| capture_000.f32 | 0 | 198,656 | 0 |
| capture_001.f32 | 254,843 | 287,744 | 56,187 (1.171 s) |

Check: the time between burst 1 (play 1) and burst 3 (play 2) in them.flac equals the wall-clock time between the two
plays within **-0.001 s** (limit 0.5 s). Onset offset me/them -0.002 ms, length difference 0. The stop output
includes the warning `EVENT capture_process_died at 4.139 s: pw-record exit code -9`.

### 5.8 Unit tests

`source scripts/env.sh && pytest -q`: **86 passed, 7 skipped** (the 7 live tests) in 2.6 s, run after the last code change. They cover: Chrome matching on the synthetic
`pw-dump` (Steam "Chromium" excluded, Chrome input stream ignored, client-property fallback, name fallback only
without a program name), left/right pairing, wanted-links set, recorder command safety (`--target 0`,
`node.autoconnect = false`, exact node name), timeline gap padding and no-overlap, partial last frame after a crash,
statistics (tone RMS/peak exact to 0.01 dB), silence/clipping/short warnings, bleed detection (60 ms synthetic
leak found at 60.0 +- 1 ms; independent signals not flagged; seeds 12345-12347), event summary with churn,
end-to-end finalize (chrome-only, fallback, chrome-silent with `them_system.flac`, unreadable half-written event
line), state file (corrupt, PID reuse, wrong start time, other boot, zombie), orphan detection, consent reminder
printed first.

## 6. What the result means

The recorder meets every synthetic acceptance check by a wide margin: the two tracks are sample-identical in start
and length (0 samples difference) because they are channels of one capture node, the separation is complete, and a
Chrome stream that arrives late or reconnects is picked up without breaking the timeline. Crashes leave playable
audio that `doctor` recovers, and no runtime object outlives the recording.

## 7. Problems and assumptions

1. **Not yet tested with the real microphone and speakers.** A short run with the real default microphone and output
   monitor (no sound played) was denied by the permission system, and I did not try another route. The real Messenger
   call (section 8) is therefore the first real-device test. Things it will show: whether WirePlumber and the devices
   behave when the recorder joins the USB mic and the onboard output into one group (PipeWire then lets one device
   pace both and resamples the other; normally inaudible), and the real noise floor of the mic.
2. While recording, the default output is kept running (its monitor is linked) and the mic and output share one
   driver. This is how any program that records and plays at once works; it does not change volume or routing.
3. **All Chrome playback streams are captured**, not just the Messenger tab: a YouTube tab playing during the call
   would also be in `them.flac`. `meta.json` lists every stream with its `media.name` so this can be seen.
4. **`me` is the default microphone**, followed if the default changes. If Messenger is set to a different mic than
   the system default, `me.flac` still records the default one.
5. A new Chrome stream is linked up to 0.3 s after it appears (poll interval). The monitor channels have that
   moment; it is not copied into `them.flac`.
6. Bleed and silence thresholds were set on synthetic signals; the real call may need tuning.
7. Raw capture uses about 4.1 GB per hour (6 channels x 4 bytes x 48,000 per second) until stop converts it; `start`
   refuses to run with less than 5 GB free.
8. The audit expected Chromium 155 to carry call audio; it was Steam. If the user actually uses Chromium for calls,
   its binary `chromium` is already in the match list.
9. Python package added to `.venv`: numpy 2.5.5 (project-local, not a system package). No system package installed.
10. **Bug found and fixed during testing:** doctor's process search first matched any command line that merely
    *contained* `pw-loopback` and `omni_rec_`, which included my own bash shells. Now a process matches only if its
    program (argv[0]) is that tool, or, for the supervisor, if it is exactly `python -m omni_recorder.capture_daemon`.
    Unit test `test_find_procs_matches_program_not_text` covers it.
11. **Test artifacts left in place:** deleting them was denied, so `.tmp/live_test/` (282 MB, of which 263 MB is
    the 30-minute run's synthetic tone FLACs in `.tmp/live_test/test_live_long_drift/`) and `.tmp/exp/` (17 MB of
    early experiment files, synthetic tones only) remain. Both are git-ignored and contain no real audio. They can
    be deleted at any time.

## 8. What the user must check in one real Messenger call

1. `source scripts/env.sh && omni-rec start` shortly before the call. Check the printed microphone is the Blue
   Snowball (or whichever mic you talk into).
2. During the call run `omni-rec status`: it should say `them mode now: chrome-only` and list a stream from
   `Google Chrome`. If it says "no Chrome stream yet" while you hear the other person, tell the coordinator.
3. Talk for 1-2 minutes, both sides speaking. If possible spend half the time on speakers and half on headphones.
4. `omni-rec stop`. Read any `!!` warnings.
5. Listen briefly to `me.flac` (only you) and `them.flac` (only the other person).
6. Tell the coordinator whether the call sounded normal during recording (no clicks or dropouts).
7. The coordinator should read `records/<call_id>/meta.json` locally (it is private, never committed) and look at:
   `them_mode`, `capture.chrome_streams` (names and intervals), `capture.chrome_linked_s`, `warnings`,
   `bleed_check`, `files.*.stats`, `alignment`, and events of type `link_failed` or `daemon_error`.

## Installed on this system

System packages (from `reports/INSTALLED.md`): cmake 4.4.4-1, cppdap 1.58.0-3, jsoncpp 1.9.8-1, rhash 1.4.6-1
(all official, installed by the coordinator before this stage). **New in this stage: nothing.**
Python, project `.venv` only: numpy 2.5.5 (new in this stage).
