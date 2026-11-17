"""Background capture supervisor started by `omni-rec start`.

Run as:  python -m omni_recorder.capture_daemon <call_dir> --config <config.toml> --runtime-dir <dir>

What it does:
1. Starts ONE `pw-record` process that creates a 6-channel capture node named
   omni_rec_capture_<call_id> and writes raw 32-bit float frames to capture_NNN.f32.
   The node is created with node.autoconnect=false, so the session manager
   (WirePlumber) never links it to anything by itself.
2. Every poll interval it reads the graph (pw-dump) and makes the links into that
   node match what is wanted:
     channels 0-1  <- microphone (default source unless config names one)
     channels 2-3  <- every Chrome/Chromium playback stream (summed by PipeWire)
     channels 4-5  <- monitor of the default output (fallback: all system sound)
   It only ever creates or removes links whose INPUT side is its own node. Chrome's
   own links to the speakers are never touched, so the user hears exactly the same.
3. Logs every change (stream appeared / disappeared, mic or output changed, link
   failure, recorder restart) to events.jsonl with the position in the recording.
4. On SIGTERM/SIGINT/SIGHUP it sends SIGINT to pw-record (so it flushes and closes
   the file), waits, logs the final position and exits.

Crash behaviour: pw-record is started with a parent-death signal (SIGINT), so if
this supervisor dies for any reason the recorder stops cleanly too, and PipeWire
removes the node and its links because their owner is gone. The raw file is
valid up to its last whole frame; `omni-rec doctor` turns it into FLAC.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import signal
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

from . import pwgraph
from .config import load_config
from .finalize import CAPTURE_JSON, EVENTS, write_json_atomic

CHANNELS = 6
FRAME_BYTES = 4 * CHANNELS
PORTS = [f"AUX{i}" for i in range(CHANNELS)]
LAYOUT = {"me": [0, 1], "chrome": [2, 3], "system": [4, 5]}
PORT_LAYOUT = {role: (f"input_{PORTS[a]}", f"input_{PORTS[b]}") for role, (a, b) in LAYOUT.items()}
MAX_RESTARTS = 50
PR_SET_PDEATHSIG = 1


def node_name_for(call_id: str) -> str:
    return pwgraph.RECORDER_PREFIX + call_id.replace("-", "_")


def pw_record_cmd(node_name: str, rate: int, path: Path) -> list[str]:
    props = ("{ node.name = \"%s\" node.description = \"omni_rec capture\" application.name = \"omni_rec\" "
             "media.name = \"omni_rec call capture\" node.autoconnect = false node.always-process = true "
             "node.dont-reconnect = true }" % node_name)
    return ["pw-record", "--target", "0", "--raw", "--format", "f32", "--rate", str(rate),
            "--channels", str(CHANNELS), "--channel-map", ",".join(PORTS), "-P", props, str(path)]


def _set_pdeathsig() -> None:
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    libc.prctl(PR_SET_PDEATHSIG, signal.SIGINT, 0, 0, 0)


class Daemon:
    def __init__(self, call_dir: Path, config_path: str | None, runtime_dir: Path):
        self.call_dir = call_dir
        self.cfg = load_config(config_path) if config_path else load_config()
        self.runtime_dir = runtime_dir
        self.cap = json.loads((call_dir / CAPTURE_JSON).read_text())
        self.rate = int(self.cap["rate"])
        self.node_name = self.cap["node_name"]
        a = self.cfg.section("audio")
        self.poll = float(a.get("poll_interval_s", 0.3))
        self.mic_wanted = str(a.get("mic_source", "default"))
        self.out_wanted = str(a.get("output_monitor", "default"))
        self.system_enabled = bool(a.get("fallback_to_default_monitor", True))
        self.binaries = list(a.get("chrome_binaries", ["chrome", "chromium"]))
        self.name_match = list(a.get("chrome_stream_match", ["Google Chrome"]))
        self.exclude = list(a.get("exclude_binaries", ["steamwebhelper"]))
        self.stop = threading.Event()
        self.proc: subprocess.Popen | None = None
        self.seg_index = -1
        self.restarts = 0
        self.seg_offset_s = 0.0          # timeline position where the current segment starts
        self.prev_mic: str | None = None
        self.mic_missing_logged = False
        self.prev_sink: str | None = None
        self.prev_chrome: dict[int, dict] = {}
        self.failed_pairs: set[tuple[int, int]] = set()
        self.events_fh = (call_dir / EVENTS).open("a", buffering=1)
        self.last_error = ""

    # ---- logging ---------------------------------------------------------------
    def pos_s(self) -> float:
        seg = self.current_segment()
        if seg is None:
            return 0.0
        p = self.call_dir / seg["file"]
        frames = p.stat().st_size // FRAME_BYTES if p.exists() else 0
        return round(self.seg_offset_s + frames / self.rate, 3)

    def event(self, name: str, **kw) -> None:
        rec = {"event": name, "pos_s": self.pos_s(), "t_wall": round(time.time(), 3),
               "t_mono": round(time.monotonic(), 3), **kw}
        self.events_fh.write(json.dumps(rec, default=str) + "\n")
        self.events_fh.flush()
        os.fsync(self.events_fh.fileno())

    def current_segment(self) -> dict | None:
        segs = self.cap.get("segments") or []
        return segs[-1] if segs else None

    def save_cap(self) -> None:
        write_json_atomic(self.call_dir / CAPTURE_JSON, self.cap)

    # ---- recorder process ---------------------------------------------------------
    def start_segment(self) -> None:
        prev = self.current_segment()
        if prev is not None and prev.get("start_mono") is not None:
            p = self.call_dir / prev["file"]
            frames = p.stat().st_size // FRAME_BYTES if p.exists() else 0
            prev_end = self.seg_offset_s + frames / self.rate
            self.seg_offset_s = max(prev_end, time.monotonic() - self.cap["segments"][0]["start_mono"])
        self.seg_index += 1
        name = f"capture_{self.seg_index:03d}.f32"
        cmd = pw_record_cmd(self.node_name, self.rate, self.call_dir / name)
        spawn_mono, spawn_wall = time.monotonic(), time.time()
        self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=open(self.call_dir / "pw-record.log", "a"),
                                     preexec_fn=_set_pdeathsig)
        self.cap.setdefault("segments", []).append({
            "file": name, "pw_record_pid": self.proc.pid, "spawn_mono": spawn_mono, "spawn_wall": spawn_wall,
            "start_mono": None, "start_wall": None, "start_uncertainty_s": None, "command": cmd})
        self.save_cap()
        self.event("capture_started", segment=self.seg_index, pw_record_pid=self.proc.pid)
        self._estimate_start()

    def _estimate_start(self, budget_s: float = 5.0) -> None:
        """Find when the first sample was captured: poll the file size quickly
        until data appears, then subtract the duration already written."""
        seg = self.current_segment()
        assert seg is not None
        path = self.call_dir / seg["file"]
        t_end = time.monotonic() + budget_s
        last_empty = time.monotonic()
        while time.monotonic() < t_end and not self.stop.is_set():
            # links must exist for the node to run; link as soon as the node shows up
            if path.exists() and path.stat().st_size > 0:
                now_m, now_w = time.monotonic(), time.time()
                frames = path.stat().st_size // FRAME_BYTES
                dur = frames / self.rate
                seg["start_mono"] = now_m - dur
                seg["start_wall"] = now_w - dur
                seg["start_uncertainty_s"] = round(now_m - last_empty, 4)
                self.save_cap()
                return
            last_empty = time.monotonic()
            if self.proc is not None and self.proc.poll() is not None:
                return
            time.sleep(0.005)
        # no data yet: fall back to the spawn time (recorded as such)
        seg["start_mono"], seg["start_wall"] = seg["spawn_mono"], seg["spawn_wall"]
        seg["start_uncertainty_s"] = None
        seg["start_note"] = "no data within 5 s of start; spawn time used"
        self.save_cap()

    def stop_recorder(self) -> None:
        p = self.proc
        if p is None or p.poll() is not None:
            return
        p.send_signal(signal.SIGINT)
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.terminate()
            try:
                p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()

    # ---- linking --------------------------------------------------------------------
    def reconcile(self) -> dict:
        g = pwgraph.dump()
        rec = g.node_by_name(self.node_name)
        if rec is None:
            return {"recorder_node": None}
        mic, mic_how = pwgraph.resolve_device(g, self.mic_wanted, "default.audio.source")
        chrome = pwgraph.find_chrome_streams(g, self.binaries, self.name_match, self.exclude)
        sink, sink_how = (pwgraph.resolve_device(g, self.out_wanted, "default.audio.sink")
                          if self.system_enabled else (None, "disabled"))
        want = pwgraph.desired_links(g, rec, mic, chrome, sink, PORT_LAYOUT)
        have = {(l.out_port, l.in_port): l.id for l in g.links_into(rec.id)}

        made: set[tuple[int, int]] = set()
        for pair in sorted(want - set(have)):
            ok, msg = pwgraph.link(*pair)
            if ok:
                made.add(pair)
                self.failed_pairs.discard(pair)
            elif pair not in self.failed_pairs:
                self.failed_pairs.add(pair)
                op = g.ports.get(pair[0])
                src = g.nodes.get(op.node_id).name if op and op.node_id in g.nodes else "?"
                self.event("link_failed", detail=f"{src} port {pair[0]} -> {pair[1]}: {msg}")
        for pair, lid in have.items():
            if pair not in want:
                pwgraph.unlink(lid)
        linked_now = (set(have) & want) | made

        def linked(node) -> bool:
            if node is None:
                return False
            ports = {p.id for p in g.ports.values() if p.node_id == node.id}
            return any(o in ports for o, _ in linked_now)

        # mic events
        mic_key = f"{mic.name}#{mic.serial}" if mic is not None else None
        if mic is None:
            if not self.mic_missing_logged:
                self.event("mic_missing", detail=f"configured mic_source={self.mic_wanted!r} not found and no default source")
                self.mic_missing_logged = True
            self.prev_mic = None
        elif mic_key != self.prev_mic and linked(mic):
            self.event("mic_linked", node=mic.describe(), how=mic_how)
            self.prev_mic = mic_key
            self.mic_missing_logged = False
        # output monitor events
        sink_key = f"{sink.name}#{sink.serial}" if sink is not None else None
        if sink is not None and sink_key != self.prev_sink and linked(sink):
            self.event("monitor_linked", node=sink.describe(), how=sink_how)
            self.prev_sink = sink_key
        # chrome stream events (serials are never reused, ids can be)
        now: dict[int, dict] = {}
        for c in chrome:
            if c.serial is not None and linked(c):
                now[c.serial] = c.describe()
        for s in now.keys() - self.prev_chrome.keys():
            self.event("chrome_stream_linked", node=now[s])
        for s in self.prev_chrome.keys() - now.keys():
            self.event("chrome_stream_gone", node=self.prev_chrome[s])
        self.prev_chrome = now
        return {"recorder_node": rec.id, "mic": mic.name if mic else None,
                "chrome_streams": [v for v in now.values()],
                "monitor_sink": sink.name if sink else None,
                "links_into_recorder": len(linked_now)}

    def write_live(self, info: dict, stopped: bool = False) -> None:
        live = {"daemon_pid": os.getpid(), "call_id": self.call_dir.name, "call_dir": str(self.call_dir),
                "pw_record_pid": self.proc.pid if self.proc else None, "segment": self.seg_index,
                "pos_s": self.pos_s(), "updated_wall": time.time(), "updated_mono": time.monotonic(),
                "stopped": stopped, "last_error": self.last_error, **info}
        write_json_atomic(self.runtime_dir / "live.json", live)

    # ---- main loop ---------------------------------------------------------------------
    def run(self) -> int:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, lambda *_: self.stop.set())
        self.event("daemon_started", pid=os.getpid(), node_name=self.node_name)
        # first segment; link quickly so the node starts running
        self.start_segment_with_links()
        info: dict = {}
        while not self.stop.is_set():
            try:
                if self.proc is not None and self.proc.poll() is not None:
                    self.event("capture_process_died", detail=f"pw-record exit code {self.proc.returncode}",
                               segment=self.seg_index)
                    if self.restarts >= MAX_RESTARTS:
                        self.event("daemon_error", detail="too many recorder restarts; giving up")
                        break
                    self.restarts += 1
                    self.prev_chrome, self.prev_mic, self.prev_sink = {}, None, None
                    self.stop.wait(1.0)
                    if self.stop.is_set():
                        break
                    self.start_segment_with_links()
                info = self.reconcile()
                self.last_error = ""
            except Exception as exc:  # keep recording; log (once per distinct message) and retry next cycle
                msg = f"{type(exc).__name__}: {exc}"
                if msg != self.last_error:
                    self.event("daemon_error", detail=msg, trace=traceback.format_exc()[-800:])
                self.last_error = msg
            try:
                self.write_live(info)
            except OSError:
                pass
            self.stop.wait(self.poll)
        self.stop_recorder()
        self.event("capture_stopped", segment=self.seg_index,
                   pw_record_exit=self.proc.returncode if self.proc else None)
        self.write_live(info, stopped=True)
        self.events_fh.close()
        return 0

    def start_segment_with_links(self) -> None:
        """Start pw-record and link it as soon as its node appears, before
        measuring the start time, so the first samples already carry real audio.
        A helper thread does the linking while start_segment() watches the file."""
        stop_linker = threading.Event()

        def linker() -> None:
            while not stop_linker.is_set():
                try:
                    if self.reconcile().get("recorder_node") is not None:
                        return
                except Exception:
                    pass
                stop_linker.wait(0.02)

        t = threading.Thread(target=linker, daemon=True)
        t.start()
        try:
            self.start_segment()
        finally:
            stop_linker.set()
            t.join(timeout=10)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("call_dir")
    ap.add_argument("--config")
    ap.add_argument("--runtime-dir", required=True)
    a = ap.parse_args(argv)
    d = Daemon(Path(a.call_dir), a.config, Path(a.runtime_dir))
    return d.run()


if __name__ == "__main__":
    sys.exit(main())
