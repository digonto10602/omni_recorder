"""LIVE acceptance test for recording (stage 2). Needs a running PipeWire session.

Skipped unless OMNI_LIVE_AUDIO=1:
    source scripts/env.sh && OMNI_LIVE_AUDIO=1 pytest -q -s tests/test_live_recording.py

Nothing is played through the speakers and the real microphone is not used. The
test builds its own runtime-only objects, all named omni_rec_test_*, owned by
processes the test starts and stops (so PipeWire removes them with the process):

  player (pw-play, stereo file)
     FL ──> relay "chrome" (pw-loopback) ──> its output node looks like Chrome
     │                                        (application.process.binary =
     │                                        omni_rec_test_chrome) and plays into
     │                                        the test sink, like a real browser
     FR ──> relay "mic" (pw-loopback)    ──> its output node is used as the "mic"
  test sink "omni_rec_test_sink" (pw-loopback whose output goes nowhere)

The two relays are identical, so the burst that the player writes at the same
sample on FL and FR reaches the recorder through equal paths. The measured onset
difference between me.flac and them.flac is therefore the recorder's own alignment error.
Measurements are written to .tmp/live_test/results.json for the stage report.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("OMNI_LIVE_AUDIO") != "1",
                                reason="live PipeWire test; set OMNI_LIVE_AUDIO=1")

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".tmp" / "live_test"
RATE = 48000
F_THEM, F_ME = 1000.0, 440.0
TONE_AMP, BURST_AMP, BURST_S = 0.1, 0.8, 0.010
RESULTS: dict = {}


# ---- helpers -------------------------------------------------------------------------

def write_test_wav(path: Path, secs: float, burst_times: list[float]) -> None:
    """Stereo 48 kHz float WAV: FL = 1 kHz (them), FR = 440 Hz (me), loud bursts at burst_times."""
    t = np.arange(int(secs * RATE)) / RATE
    fl = TONE_AMP * np.sin(2 * math.pi * F_THEM * t)
    fr = TONE_AMP * np.sin(2 * math.pi * F_ME * t)
    for bt in burst_times:
        i0, i1 = int(bt * RATE), int((bt + BURST_S) * RATE)
        tt = np.arange(i1 - i0) / RATE
        fl[i0:i1] = BURST_AMP * np.sin(2 * math.pi * F_THEM * tt)
        fr[i0:i1] = BURST_AMP * np.sin(2 * math.pi * F_ME * tt)
    raw = np.stack([fl, fr], axis=1).astype("<f4").tobytes()
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "f32le", "-ar", str(RATE), "-ac", "2",
                    "-i", "pipe:0", "-c:a", "pcm_f32le", str(path)], input=raw, check=True)


def load_flac(path: Path) -> np.ndarray:
    p = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "pipe:1"],
                       capture_output=True, check=True)
    return np.frombuffer(p.stdout, dtype="<f4").astype(np.float64)


def volumedetect(path: Path) -> dict:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "volumedetect",
                        "-f", "null", "-"], capture_output=True, text=True)
    out = {}
    for line in p.stderr.splitlines():
        for key in ("mean_volume", "max_volume"):
            if key + ":" in line:
                out[key + "_db"] = float(line.split(key + ":")[1].split()[0])
    return out


def tone_level_db(x: np.ndarray, f: float) -> float:
    """Amplitude of the sine component at f, in dBFS (Hann-windowed FFT, band +-3 Hz)."""
    if x.size == 0:
        return float("-inf")
    w = np.hanning(x.size)
    spec = np.abs(np.fft.rfft(x * w)) * 2 / w.sum()
    freqs = np.fft.rfftfreq(x.size, 1 / RATE)
    band = (freqs > f - 3) & (freqs < f + 3)
    a = float(spec[band].max())
    return 20 * math.log10(a) if a > 0 else float("-inf")


def onsets(x: np.ndarray, thr: float = 0.4, gap_s: float = 0.5) -> list[int]:
    idx = np.nonzero(np.abs(x) > thr)[0]
    out: list[int] = []
    last = None
    for i in idx:
        if last is None or i - last > gap_s * RATE:
            out.append(int(i))      # first loud sample after a quiet gap = burst onset
        last = i
    return out


def graph_names() -> list[str]:
    d = json.loads(subprocess.run(["pw-dump", "--no-colors"], capture_output=True, text=True).stdout)
    return [o["info"]["props"].get("node.name", "") for o in d
            if o.get("type") == "PipeWire:Interface:Node" and o.get("info")]


def wait_for_node(name: str, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if name in graph_names():
            return
        time.sleep(0.05)
    raise TimeoutError(f"node {name} did not appear")


def our_procs(runtime_dir: Path) -> list[str]:
    out = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            state = (d / "stat").read_text().rsplit(")", 1)[1].split()[0]
        except OSError:
            continue
        if state == "Z":
            continue
        argv = cmd.split()
        if not argv:
            continue
        prog = Path(argv[0]).name
        if (len(argv) > 2 and argv[1:3] == ["-m", "omni_recorder.capture_daemon"] and str(runtime_dir) in cmd) or \
                (prog == "pw-record" and "omni_rec_capture_" in cmd):
            out.append(f"{d.name}: {cmd[:100]}")
    return out


class Rig:
    """Runtime-only test objects. Every process is ours and is stopped in close()."""

    def __init__(self) -> None:
        self.procs: dict[str, subprocess.Popen] = {}

    def _spawn(self, key: str, cmd: list[str]) -> None:
        self.procs[key] = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def sink(self) -> None:
        self._spawn("sink", ["pw-loopback", "-n", "omni_rec_test_sinkloop",
                             "--capture-props", '{ node.name = "omni_rec_test_sink" media.class = "Audio/Sink" }',
                             "--playback-props", '{ node.name = "omni_rec_test_sink_out" node.autoconnect = false }'])
        wait_for_node("omni_rec_test_sink")

    def relay(self, kind: str) -> None:
        if kind == "chrome":
            play = ('{ node.name = "omni_rec_test_chrome" application.name = "omni_rec_test_chrome" '
                    'application.process.binary = "omni_rec_test_chrome" target.object = "omni_rec_test_sink" }')
        else:
            play = '{ node.name = "omni_rec_test_mic" node.autoconnect = false }'
        self._spawn(kind, ["pw-loopback", "-n", f"omni_rec_test_relay_{kind}", "-c", "1", "-m", "[ MONO ]",
                           "--capture-props", '{ node.name = "omni_rec_test_%s_in" node.autoconnect = false }' % kind,
                           "--playback-props", play])
        wait_for_node(f"omni_rec_test_{kind}_in")
        wait_for_node(f"omni_rec_test_{kind}")

    def drop(self, key: str) -> None:
        p = self.procs.pop(key, None)
        if p and p.poll() is None:
            p.send_signal(signal.SIGINT)
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()

    def play(self, wav: Path) -> subprocess.Popen:
        self.drop("player")
        self._spawn("player", ["pw-play", "--target", "0", "-P",
                               '{ node.name = "omni_rec_test_player" node.always-process = true }', str(wav)])
        wait_for_node("omni_rec_test_player")
        for ch, kind in (("FL", "chrome"), ("FR", "mic")):
            if kind in self.procs:
                subprocess.run(["pw-link", f"omni_rec_test_player:output_{ch}", f"omni_rec_test_{kind}_in:input_MONO"],
                               check=True, capture_output=True)
        return self.procs["player"]

    def close(self) -> None:
        for key in list(self.procs):
            self.drop(key)


def write_config(path: Path, records: Path, rt: Path, binaries: list[str]) -> None:
    path.write_text(f"""
[paths]
records_dir = "{records}"
models_dir = "models"
runtime_dir = "{rt}"
[audio]
sample_rate = 48000
chrome_binaries = {json.dumps(binaries)}
chrome_stream_match = []
exclude_binaries = ["steamwebhelper"]
fallback_to_default_monitor = true
mic_source = "omni_rec_test_mic"
output_monitor = "omni_rec_test_sink"
poll_interval_s = 0.3
keep_raw_capture = false
[languages]
[speech]
[translation]
[llm]
""")


def cli(env: dict, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run([sys.executable, "-m", "omni_recorder", *args], capture_output=True, text=True,
                       env=env, cwd=str(ROOT), timeout=180)
    if check and p.returncode != 0:
        raise AssertionError(f"omni-rec {' '.join(args)} exit {p.returncode}\n{p.stdout}\n{p.stderr}")
    return p


@pytest.fixture
def setup(request):
    name = request.node.name
    base = WORK / name
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    records, rt = base / "records", base / "rt"
    binaries = ["no_such_browser"] if "fallback" in name else ["omni_rec_test_chrome"]
    write_config(base / "config.toml", records, rt, binaries)
    env = dict(os.environ, OMNI_CONFIG=str(base / "config.toml"), OMNI_ROOT=str(ROOT))
    rig = Rig()
    yield base, records, rt, env, rig
    cli(env, "stop", check=False)
    rig.close()
    # final cleanliness check for every test
    time.sleep(0.5)
    assert our_procs(rt) == []
    assert not [n for n in graph_names() if n.startswith("omni_rec_")]


def save_results(key: str, value) -> None:
    RESULTS[key] = value
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / "results.json"
    old = json.loads(path.read_text()) if path.exists() else {}
    old[key] = value
    path.write_text(json.dumps(old, indent=2))


def only_call(records: Path) -> Path:
    calls = [d for d in records.iterdir() if d.is_dir()]
    assert len(calls) == 1, calls
    return calls[0]


def analyse(call: Path) -> dict:
    me, them = load_flac(call / "me.flac"), load_flac(call / "them.flac")
    meta = json.loads((call / "meta.json").read_text())
    on_me, on_them = onsets(me), onsets(them)
    n = min(len(on_me), len(on_them))
    # The detector fires when |x| first exceeds 0.4, i.e. asin(0.4/0.8)/(2 pi f) after a
    # burst starts: 0.189 ms at 440 Hz, 0.083 ms at 1 kHz. Remove that known bias.
    bias_ms = 1000 * (math.asin(0.4 / BURST_AMP) / (2 * math.pi)) * (1 / F_ME - 1 / F_THEM)
    raw_offs = [1000 * (on_me[i] - on_them[i]) / RATE for i in range(n)]
    offs = [o - bias_ms for o in raw_offs]
    # Separation is judged on burst-free audio (between the first two bursts): a 10 ms
    # burst with hard edges spreads energy over all frequencies and would hide the result.
    if n >= 2:
        a, b = on_them[0] + int(0.2 * RATE), on_them[1] - int(0.2 * RATE)
    else:
        a, b = 0, them.size
    return {
        "call_id": call.name, "them_mode": meta["them_mode"], "duration_s": meta["duration_s"],
        "me_samples": int(me.size), "them_samples": int(them.size),
        "length_difference_ms": 1000 * (me.size - them.size) / RATE,
        "me_volumedetect": volumedetect(call / "me.flac"), "them_volumedetect": volumedetect(call / "them.flac"),
        "mix_volumedetect": volumedetect(call / "mix.flac"),
        "separation_window_s": [round(a / RATE, 3), round(b / RATE, 3)],
        "me_440_db": tone_level_db(me[a:b], F_ME), "me_1000_db": tone_level_db(me[a:b], F_THEM),
        "them_1000_db": tone_level_db(them[a:b], F_THEM), "them_440_db": tone_level_db(them[a:b], F_ME),
        "onset_offsets_raw_ms": [round(o, 3) for o in raw_offs], "detector_bias_ms": round(bias_ms, 3),
        "bursts_me": len(on_me), "bursts_them": len(on_them),
        "onset_offsets_ms": [round(o, 3) for o in offs],
        "max_abs_onset_offset_ms": round(max((abs(o) for o in offs), default=float("nan")), 3),
        "warnings": meta["warnings"], "events": [e["event"] for e in meta["events"]],
        "start_wall": meta["start_wall"], "start_uncertainty_s": meta["start_time_uncertainty_s"],
    }


# ---- tests -----------------------------------------------------------------------------

BURSTS = [2.0, 4.0, 6.0, 8.0, 10.0]


def test_live_record_separation_alignment_cleanup(setup):
    base, records, rt, env, rig = setup
    wav = base / "tones.wav"
    write_test_wav(wav, 12.0, BURSTS)
    rig.sink(); rig.relay("mic"); rig.relay("chrome")
    out = cli(env, "start").stdout
    assert "other person must know" in out
    st = cli(env, "status").stdout
    assert "chrome-only" in st
    rig.play(wav).wait(30)
    time.sleep(1.0)
    stop = cli(env, "stop")
    r = analyse(only_call(records))
    r["stop_stdout"] = stop.stdout
    time.sleep(0.5)
    r["leftover_nodes_after_stop"] = [n for n in graph_names() if n.startswith("omni_rec_capture_")]
    r["leftover_procs_after_stop"] = our_procs(rt)
    save_results("main", r)
    assert r["them_mode"] == "chrome-only"
    assert r["me_volumedetect"]["mean_volume_db"] > -40 and r["them_volumedetect"]["mean_volume_db"] > -40
    assert r["them_1000_db"] - r["them_440_db"] > 60, "them.flac must not contain the mic tone"
    assert r["me_440_db"] - r["me_1000_db"] > 60, "me.flac must not contain the Chrome tone"
    assert r["bursts_me"] == r["bursts_them"] == len(BURSTS)
    assert r["max_abs_onset_offset_ms"] <= 20.0
    assert abs(r["length_difference_ms"]) <= 20.0
    assert r["leftover_nodes_after_stop"] == [] and r["leftover_procs_after_stop"] == []


def test_live_chrome_churn(setup):
    """Chrome's stream appears after start, disappears, and comes back with a new serial."""
    base, records, rt, env, rig = setup
    wav = base / "short.wav"
    write_test_wav(wav, 4.0, [1.0, 3.0])
    rig.sink(); rig.relay("mic")
    t0 = time.monotonic()
    cli(env, "start")
    time.sleep(2.0)
    rig.relay("chrome")               # stream appears after start
    rig.play(wav).wait(30)
    rig.drop("chrome")                # disappears (e.g. reconnect)
    time.sleep(2.0)
    rig.relay("chrome")               # reappears as a new stream
    rig.play(wav).wait(30)
    time.sleep(0.5)
    cli(env, "stop")
    wall = time.monotonic() - t0
    call = only_call(records)
    meta = json.loads((call / "meta.json").read_text())
    ev = [(e["event"], e.get("pos_s")) for e in meta["events"]]
    r = analyse(call)
    r["event_positions"] = ev
    r["wall_time_s"] = round(wall, 2)
    r["chrome_streams"] = [(c["serial"], c["intervals"]) for c in meta["capture"]["chrome_streams"]]
    save_results("churn", r)
    names = [e for e, _ in ev]
    assert names.count("chrome_stream_linked") == 2 and names.count("chrome_stream_gone") == 1
    assert len(meta["capture"]["chrome_streams"]) == 2
    assert r["bursts_me"] == r["bursts_them"] == 4
    assert r["max_abs_onset_offset_ms"] <= 20.0
    assert abs(r["length_difference_ms"]) <= 20.0
    assert meta["duration_s"] <= wall + 0.5     # no invented audio
    assert len(meta["segments"]) == 1           # one continuous recorder process throughout


def test_live_fallback_monitor(setup):
    """No Chrome match: them.flac is the output monitor, and meta.json says so."""
    base, records, rt, env, rig = setup
    wav = base / "short.wav"
    write_test_wav(wav, 4.0, [1.0, 3.0])
    rig.sink(); rig.relay("mic"); rig.relay("chrome")
    cli(env, "start")
    rig.play(wav).wait(30)
    time.sleep(0.5)
    out = cli(env, "stop").stdout
    r = analyse(only_call(records))
    save_results("fallback", r)
    assert r["them_mode"] == "fallback-system-monitor"
    assert any(w.startswith("FALLBACK") for w in r["warnings"]) and "FALLBACK" in out
    assert r["them_1000_db"] - r["them_440_db"] > 60
    assert r["max_abs_onset_offset_ms"] <= 20.0


@pytest.mark.parametrize("victims", ["supervisor", "supervisor+recorder"])
def test_live_crash_recovery(setup, victims):
    base, records, rt, env, rig = setup
    wav = base / "short.wav"
    write_test_wav(wav, 4.0, [1.0, 3.0])
    rig.sink(); rig.relay("mic"); rig.relay("chrome")
    cli(env, "start")
    rig.play(wav).wait(30)
    state = json.loads((rt / "state.json").read_text())
    live = json.loads((rt / "live.json").read_text())
    os.kill(state["daemon_pid"], signal.SIGKILL)
    if victims == "supervisor+recorder":
        os.kill(live["pw_record_pid"], signal.SIGKILL)
    time.sleep(1.5)
    r: dict = {"victims": victims}
    r["procs_after_kill"] = our_procs(rt)
    r["recorder_nodes_after_kill"] = [n for n in graph_names() if n.startswith("omni_rec_capture_")]
    st = cli(env, "status", check=False)
    r["status_exit"], r["status_out"] = st.returncode, st.stdout.strip()
    doc = cli(env, "doctor", check=False)
    r["doctor_cleanup_lines"] = [l for l in doc.stdout.splitlines() if "cleanup" in l]
    call = only_call(records)
    meta = json.loads((call / "meta.json").read_text())
    r["recovered_after_crash"] = meta["recovered_after_crash"]
    r["recovered_duration_s"] = meta["duration_s"]
    r["recovered_me_db"] = volumedetect(call / "me.flac")
    r["recovered_them_db"] = volumedetect(call / "them.flac")
    r["raw_left"] = [p.name for p in call.glob("capture_*.f32")]
    r["state_left"] = (rt / "state.json").exists()
    # fresh start/stop works afterwards (doctor also stopped the test rig: rebuild it)
    rig.close()
    rig.sink(); rig.relay("mic"); rig.relay("chrome")
    cli(env, "start")
    rig.play(wav).wait(30)
    time.sleep(0.5)
    cli(env, "stop")
    calls = sorted(d for d in records.iterdir() if d.is_dir())
    r["fresh_call"] = calls[-1].name
    r["fresh_ok"] = len(calls) == 2 and (calls[-1] / "meta.json").exists()
    save_results(f"crash_{victims}", r)
    assert r["procs_after_kill"] == [] and r["recorder_nodes_after_kill"] == []
    assert r["status_exit"] == 3
    assert r["recovered_after_crash"] is True and r["recovered_duration_s"] > 3.0
    assert r["recovered_them_db"]["mean_volume_db"] > -40
    assert r["raw_left"] == [] and r["state_left"] is False and r["fresh_ok"]


@pytest.mark.skipif(not os.environ.get("OMNI_LIVE_LONG_S"), reason="long run; set OMNI_LIVE_LONG_S=<seconds>")
def test_live_long_drift(setup):
    """Bursts on both sides for OMNI_LIVE_LONG_S seconds: alignment at the end vs the start."""
    base, records, rt, env, rig = setup
    total = float(os.environ["OMNI_LIVE_LONG_S"])
    wav = base / "loop.wav"
    write_test_wav(wav, 10.0, [1.0, 6.0])
    rig.sink(); rig.relay("mic"); rig.relay("chrome")
    t0 = time.monotonic()
    cli(env, "start")
    state = json.loads((rt / "state.json").read_text())
    plays = 0
    while time.monotonic() - t0 < total:
        rig.play(wav).wait(60)
        plays += 1

    def cpu(pid: int) -> dict:
        f = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        rss = [l for l in Path(f"/proc/{pid}/status").read_text().splitlines() if l.startswith("VmRSS")]
        tck = os.sysconf("SC_CLK_TCK")
        return {"cpu_s": (int(f[11]) + int(f[12])) / tck, "rss": rss[0].split(None, 1)[1] if rss else None}

    live = json.loads((rt / "live.json").read_text())
    usage = {"supervisor": cpu(state["daemon_pid"]), "pw_record": cpu(live["pw_record_pid"])}
    wall = time.monotonic() - t0
    s0 = time.monotonic()
    cli(env, "stop")
    stop_s = time.monotonic() - s0
    r = analyse(only_call(records))
    offs = r["onset_offsets_ms"]
    r.update({"plays": plays, "wall_s": round(wall, 1), "stop_and_finalize_s": round(stop_s, 1), "usage": usage,
              "offset_first_ms": offs[0] if offs else None, "offset_last_ms": offs[-1] if offs else None,
              "drift_ms": round(offs[-1] - offs[0], 3) if offs else None,
              "flac_bytes": {p.name: p.stat().st_size for p in only_call(records).glob("*.flac")}})
    r.pop("onset_offsets_ms"); r.pop("onset_offsets_raw_ms")
    r["n_onsets"] = len(offs)
    save_results("long", r)
    assert r["bursts_me"] == r["bursts_them"] == 2 * plays
    assert r["max_abs_onset_offset_ms"] <= 20.0 and abs(r["drift_ms"]) <= 50.0
    assert abs(r["length_difference_ms"]) <= 20.0


def test_live_recorder_restart_keeps_timeline(setup):
    """pw-record dies while the supervisor lives (e.g. audio server restart): a new
    segment starts and the gap is filled with silence, so later audio keeps its real time."""
    base, records, rt, env, rig = setup
    wav = base / "short.wav"
    write_test_wav(wav, 4.0, [1.0, 3.0])
    rig.sink(); rig.relay("mic"); rig.relay("chrome")
    t0 = time.monotonic()
    cli(env, "start")
    t_play1 = time.monotonic() - t0
    rig.play(wav).wait(30)
    live = json.loads((rt / "live.json").read_text())
    t_kill = time.monotonic() - t0
    os.kill(live["pw_record_pid"], signal.SIGKILL)
    time.sleep(2.5)
    t_play2 = time.monotonic() - t0
    rig.play(wav).wait(30)
    time.sleep(0.5)
    cli(env, "stop")
    wall = time.monotonic() - t0
    call = only_call(records)
    meta = json.loads((call / "meta.json").read_text())
    r = analyse(call)
    them = load_flac(call / "them.flac")
    on = onsets(them)
    r.update({"segments": [{k: s[k] for k in ("file", "offset", "frames", "gap_before")} for s in meta["segments"]],
              "kill_at_s": round(t_kill, 2), "second_play_at_s": round(t_play2, 2), "wall_s": round(wall, 2),
              "them_onsets_s": [round(i / RATE, 3) for i in on]})
    save_results("restart", r)
    assert len(meta["segments"]) == 2 and meta["segments"][1]["gap_before"] > 0
    assert "capture_process_died" in r["events"] and r["events"].count("capture_started") == 2
    assert any("capture_process_died" in w for w in r["warnings"])
    assert r["bursts_me"] == r["bursts_them"] == 4 and r["max_abs_onset_offset_ms"] <= 20.0
    # time between burst 1 (1 s into play 1) and burst 3 (1 s into play 2) in the file must
    # equal the real time between the two plays: the gap was filled, not dropped
    r["file_vs_wall_error_s"] = round((r["them_onsets_s"][2] - r["them_onsets_s"][0]) - (t_play2 - t_play1), 3)
    save_results("restart", r)
    assert abs(r["file_vs_wall_error_s"]) < 0.5
    assert meta["duration_s"] <= wall + 0.5
