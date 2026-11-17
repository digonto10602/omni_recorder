"""Start / stop / status of a recording, the state file, and leftover cleanup.

Runtime state lives in a project-local folder (config [paths] runtime_dir,
default .tmp/recorder):
  state.json   written by `start`: call folder, supervisor PID + its kernel start
               time and the boot id (so a reused PID after a reboot is never mistaken
               for ours)
  live.json    rewritten by the supervisor every poll: what is linked right now
  lock         file lock so two commands never start/stop at the same time
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import pwgraph
from .capture_daemon import LAYOUT, node_name_for
from .config import Config
from .finalize import CAPTURE_JSON, finalize, needs_finalize, tool_versions, write_json_atomic
from .paths import new_call_id

DAEMON_MODULE = "omni_recorder.capture_daemon"
START_TIMEOUT_S = 10.0
STOP_TIMEOUT_S = 20.0
MIN_FREE_GB = 5.0


class RecorderError(RuntimeError):
    pass


# ---- paths / state -------------------------------------------------------------------

def runtime_dir(cfg: Config) -> Path:
    d = cfg.resolve(cfg.get("paths", "runtime_dir", ".tmp/recorder"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path(cfg: Config) -> Path:
    return runtime_dir(cfg) / "state.json"


def load_state(cfg: Config) -> dict | None:
    p = _state_path(cfg)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {"corrupt": True}


def clear_state(cfg: Config) -> None:
    for name in ("state.json", "live.json"):
        p = runtime_dir(cfg) / name
        if p.exists():
            p.unlink()


def load_live(cfg: Config) -> dict | None:
    p = runtime_dir(cfg) / "live.json"
    try:
        return json.loads(p.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


@contextmanager
def _lock(cfg: Config) -> Iterator[None]:
    with (runtime_dir(cfg) / "lock").open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# ---- process helpers -----------------------------------------------------------------

def boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return ""


def proc_starttime(pid: int) -> int | None:
    """Kernel start time of a process (clock ticks since boot), None if gone or a zombie."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    rest = stat.rsplit(")", 1)[1].split()
    if rest[0] == "Z":
        return None
    return int(rest[19])


def proc_cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        return ""


def pid_alive(pid: int | None, starttime: int | None = None) -> bool:
    if not pid:
        return False
    st = proc_starttime(int(pid))
    if st is None:
        return False
    return starttime is None or st == starttime


def daemon_alive(state: dict | None) -> bool:
    if not state or state.get("corrupt"):
        return False
    if state.get("boot_id") and state["boot_id"] != boot_id():
        return False
    return pid_alive(state.get("daemon_pid"), state.get("daemon_starttime")) and \
        is_daemon_argv(proc_argv(int(state["daemon_pid"])))


def proc_argv(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [a.decode(errors="replace") for a in raw.split(b"\0") if a]


def is_daemon_argv(argv: list[str]) -> bool:
    """`python -m omni_recorder.capture_daemon ...` exactly (not a shell that mentions it)."""
    return len(argv) >= 3 and "python" in Path(argv[0]).name and argv[1] == "-m" and argv[2] == DAEMON_MODULE


def find_procs(exe: str, *needles: str) -> list[tuple[int, str]]:
    """Processes of this user whose program is `exe` and whose arguments contain ALL needles.

    The program is the file name of argv[0] (e.g. "pw-record", "pw-loopback"), or
    the special value DAEMON_MODULE for the capture supervisor. A shell whose
    command text merely mentions these words is never matched."""
    out = []
    me = os.getpid()
    uid = os.getuid()
    for d in Path("/proc").iterdir():
        if not d.name.isdigit() or int(d.name) == me:
            continue
        try:
            if d.stat().st_uid != uid:
                continue
        except OSError:
            continue
        argv = proc_argv(int(d.name))
        if not argv:
            continue
        if exe == DAEMON_MODULE:
            if not is_daemon_argv(argv):
                continue
        elif Path(argv[0]).name != exe:
            continue
        cmd = " ".join(argv)
        if all(n in cmd for n in needles) and proc_starttime(int(d.name)) is not None:
            out.append((int(d.name), cmd))
    return out


def signal_and_wait(pid: int, sig: int, timeout: float, starttime: int | None = None) -> bool:
    """Send `sig`, wait up to `timeout` s for exit. True if the process is gone."""
    if starttime is None:
        starttime = proc_starttime(pid)
    if starttime is None:
        return True
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return True
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not pid_alive(pid, starttime):
            return True
        time.sleep(0.05)
    return not pid_alive(pid, starttime)


def stop_process(pid: int, first: int = signal.SIGINT, timeout: float = 10.0) -> str:
    st = proc_starttime(pid)
    if st is None:
        return "already gone"
    if signal_and_wait(pid, first, timeout, st):
        return f"stopped with {signal.Signals(first).name}"
    if signal_and_wait(pid, signal.SIGTERM, 3.0, st):
        return "stopped with SIGTERM"
    signal_and_wait(pid, signal.SIGKILL, 3.0, st)
    return "killed with SIGKILL"


# ---- start ---------------------------------------------------------------------------

def _audio_cfg(cfg: Config) -> dict:
    a = cfg.section("audio")
    return {k: a.get(k) for k in ("sample_rate", "mic_source", "output_monitor", "chrome_binaries",
                                   "chrome_stream_match", "exclude_binaries", "fallback_to_default_monitor",
                                   "poll_interval_s", "keep_raw_capture")}


def start_recording(cfg: Config) -> str:
    """Begin recording. Returns the call_id. Details of what got linked: recording_status()."""
    for tool in ("pw-record", "pw-dump", "pw-link", "ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise RecorderError(f"required tool missing: {tool}")
    with _lock(cfg):
        st = load_state(cfg)
        if daemon_alive(st):
            raise RecorderError(f"already recording call {st['call_id']} (run: omni-rec stop)")
        notes = cleanup_processes(cfg, live_state=None, scope="capture")
        if st:
            clear_state(cfg)
        records = cfg.records_dir
        records.mkdir(parents=True, exist_ok=True)
        free_gb = shutil.disk_usage(records).free / 1e9
        if free_gb < MIN_FREE_GB:
            raise RecorderError(f"only {free_gb:.1f} GB free in {records}; need at least {MIN_FREE_GB} GB "
                                "(the raw capture uses about 4 GB per hour until it is converted)")
        call_id = new_call_id(records)
        call_dir = records / call_id
        call_dir.mkdir(parents=True)
        a = cfg.section("audio")
        cap = {
            "format": "f32le", "rate": int(a.get("sample_rate", 48000)), "channels": 6,
            "layout": LAYOUT, "node_name": node_name_for(call_id),
            "method": ("one pw-record capture node (6 channels) linked by the omni_rec supervisor to: the "
                       "microphone (ch 0-1), Chrome's playback stream ports (ch 2-3), the default output's "
                       "monitor ports (ch 4-5)"),
            "system_monitor_enabled": bool(a.get("fallback_to_default_monitor", True)),
            "config": _audio_cfg(cfg), "tools": tool_versions(), "segments": [],
            "start_notes": notes,
        }
        write_json_atomic(call_dir / CAPTURE_JSON, cap)
        rdir = runtime_dir(cfg)
        live = rdir / "live.json"
        if live.exists():
            live.unlink()
        env = dict(os.environ, OMNI_ROOT=str(cfg.root))
        cmd = [sys.executable, "-m", DAEMON_MODULE, str(call_dir), "--runtime-dir", str(rdir)]
        if cfg.source:
            cmd += ["--config", str(cfg.source)]
        with (call_dir / "daemon.log").open("a") as log:
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                    start_new_session=True, close_fds=True, env=env, cwd=str(cfg.root))
        state = {"call_id": call_id, "call_dir": str(call_dir), "daemon_pid": proc.pid,
                 "daemon_starttime": proc_starttime(proc.pid), "boot_id": boot_id(),
                 "node_name": cap["node_name"], "started_wall": time.time(), "started_mono": time.monotonic(),
                 "config": str(cfg.source) if cfg.source else None}
        write_json_atomic(_state_path(cfg), state)
        # wait until the supervisor reports that audio is flowing
        end = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < end:
            info = load_live(cfg)
            if info and info.get("daemon_pid") == proc.pid and info.get("recorder_node") and info.get("pos_s", 0) > 0:
                return call_id
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        # failed: tear down and explain
        if proc.poll() is None:
            stop_process(proc.pid, signal.SIGTERM, 10)
        else:
            proc.wait()
        clear_state(cfg)
        tail = (call_dir / "daemon.log").read_text(errors="replace")[-1500:]
        raise RecorderError(f"recording did not start within {START_TIMEOUT_S:.0f} s. Supervisor log tail:\n{tail}")


# ---- stop ----------------------------------------------------------------------------

def _wait_node_gone(node_name: str, timeout: float = 5.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            if pwgraph.dump().node_by_name(node_name) is None:
                return True
        except RuntimeError:
            pass
        time.sleep(0.1)
    return False


def stop_capture_processes(cfg: Config, st: dict) -> dict:
    """Stop the supervisor (which stops pw-record), then make sure nothing is left."""
    info: dict = {"stop_requested_wall": time.time()}
    pid = st.get("daemon_pid")
    if daemon_alive(st):
        info["daemon"] = stop_process(int(pid), signal.SIGTERM, STOP_TIMEOUT_S)
    else:
        info["daemon"] = "was not running (crashed or stopped earlier)"
    node = st.get("node_name") or ""
    left = find_procs("pw-record", _quoted(node)) if node else []
    for p, _ in left:
        info.setdefault("orphan_pw_record", []).append({p: stop_process(p, signal.SIGINT, 10)})
    info["node_removed"] = _wait_node_gone(node) if node else True
    return info


def stop_recording(cfg: Config) -> Path:
    """Stop the running recording, finalize files, remove runtime objects. Returns the call folder."""
    with _lock(cfg):
        st = load_state(cfg)
        if not st or st.get("corrupt"):
            if st:
                clear_state(cfg)
            raise RecorderError("no recording is running (nothing to stop). `omni-rec doctor` recovers leftovers.")
        info = stop_capture_processes(cfg, st)
        clear_state(cfg)
    call_dir = Path(st["call_dir"])
    keep = bool(cfg.get("audio", "keep_raw_capture", False))
    finalize(call_dir, keep_raw=keep, stop_info=info)
    return call_dir


# ---- status --------------------------------------------------------------------------

def recording_status(cfg: Config) -> str | None:
    """Return the call_id of a running recording, or None."""
    st = load_state(cfg)
    return st["call_id"] if daemon_alive(st) else None


def status_details(cfg: Config) -> dict:
    st = load_state(cfg)
    if not st:
        return {"running": False}
    alive = daemon_alive(st)
    live = load_live(cfg) or {}
    d = {"running": alive, "stale": not alive, "call_id": st.get("call_id"), "call_dir": st.get("call_dir"),
         "elapsed_s": round(time.time() - st.get("started_wall", time.time()), 1),
         "recorded_s": live.get("pos_s"), "mic": live.get("mic"), "monitor_sink": live.get("monitor_sink"),
         "chrome_streams": live.get("chrome_streams") or [], "last_error": live.get("last_error"),
         "live_age_s": round(time.time() - live["updated_wall"], 1) if live.get("updated_wall") else None}
    d["them_mode_now"] = ("chrome-only" if d["chrome_streams"] else
                          "no Chrome stream yet (system-monitor fallback is being recorded in parallel)")
    return d


# ---- leftovers -----------------------------------------------------------------------

def proc_ppid(pid: int) -> int | None:
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])
    except (OSError, IndexError, ValueError):
        return None


def orphaned(pid: int) -> bool:
    """True if the process's parent died and it was adopted by PID 1 or a systemd
    subreaper. Helpers of a still-running program (e.g. a live test) are not orphaned."""
    pp = proc_ppid(pid)
    if pp is None or pp <= 1:
        return True
    try:
        comm = Path(f"/proc/{pp}/comm").read_text().strip()
    except OSError:
        return True
    return comm in ("systemd", "init")


def _quoted(node_name: str) -> str:
    """How a node name appears in a pw-record command line (exact, not a prefix)."""
    return f'node.name = "{node_name}"'


def cleanup_processes(cfg: Config, live_state: dict | None, scope: str = "all") -> list[str]:
    """Stop processes and runtime PipeWire objects of this app that do not belong to a
    live recording. Only things named omni_rec_ are ever touched.

    scope="capture": only recorder supervisors of this runtime dir and orphan
    pw-record capture processes (used by `start`).
    scope="all": also any pw-play / pw-cat / pw-loopback whose command line names an
    omni_rec_ object AND whose parent is gone (orphaned), e.g. left over by a crashed
    live test (used by `doctor`). Helpers whose parent is alive are only reported."""
    notes: list[str] = []
    rdir = str(runtime_dir(cfg))
    keep_daemon = int(live_state["daemon_pid"]) if live_state and daemon_alive(live_state) else None
    for pid, cmd in find_procs(DAEMON_MODULE, f"--runtime-dir {rdir}"):
        if pid != keep_daemon:
            notes.append(f"orphan supervisor pid {pid}: {stop_process(pid, signal.SIGTERM, STOP_TIMEOUT_S)}")
    live_daemons = {pid for pid, _ in find_procs(DAEMON_MODULE)}

    def supervised(pid: int) -> bool:
        return proc_ppid(pid) in live_daemons

    for pid, cmd in find_procs("pw-record", pwgraph.RECORDER_PREFIX):
        if not supervised(pid):
            notes.append(f"orphan pw-record pid {pid}: {stop_process(pid, signal.SIGINT, 10)}")
    if scope == "all":
        for tool in ("pw-play", "pw-cat", "pw-loopback", "pw-record"):
            for pid, cmd in find_procs(tool, pwgraph.APP_PREFIX):
                if pwgraph.RECORDER_PREFIX in cmd:
                    continue          # capture processes handled above
                if orphaned(pid):
                    notes.append(f"leftover {tool} pid {pid} ({cmd[:90]}): {stop_process(pid, signal.SIGINT, 10)}")
                else:
                    notes.append(f"{tool} pid {pid} ({cmd[:60]}) still has a live parent (pid {proc_ppid(pid)}), "
                                 "e.g. a running test; left alone")
    # leftover PipeWire objects (normally none: our nodes die with their owning process)
    try:
        g = pwgraph.dump()
    except RuntimeError as exc:
        notes.append(f"could not read PipeWire graph: {exc}")
        return notes
    prefix = pwgraph.APP_PREFIX if scope == "all" else pwgraph.RECORDER_PREFIX
    for n in g.nodes.values():
        if not n.name.startswith(prefix):
            continue
        owner = n.prop("application.process.id")
        owner = int(owner) if owner else None
        if owner and proc_starttime(owner) is not None:
            if supervised(owner):
                continue                  # belongs to a running recording
            owner_cmd = proc_cmdline(owner)
            is_capture = n.name.startswith(pwgraph.RECORDER_PREFIX)
            if pwgraph.APP_PREFIX in owner_cmd and (is_capture or orphaned(owner)):
                notes.append(f"node {n.name} (id {n.id}) owned by pid {owner}: {stop_process(owner, signal.SIGINT, 10)}")
            elif pwgraph.APP_PREFIX in owner_cmd:
                pass                      # helper with a live parent: reported above, left alone
            else:
                notes.append(f"node {n.name} (id {n.id}) belongs to pid {owner} ({owner_cmd[:60]}); not ours, left alone")
            continue
        p = subprocess.run(["pw-cli", "destroy", str(n.id)], capture_output=True, text=True, timeout=10)
        notes.append(f"lingering node {n.name} (id {n.id}) destroyed with pw-cli: exit {p.returncode}")
    return notes


def cleanup_leftovers(cfg: Config, recover: bool = True) -> list[str]:
    """For `omni-rec doctor`: clean orphans, then turn unfinished captures into FLAC."""
    notes: list[str] = []
    with _lock(cfg):
        st = load_state(cfg)
        live = st if daemon_alive(st) else None
        if live:
            notes.append(f"recording in progress (call {live['call_id']}); left alone")
        elif st:
            notes.append(f"stale state from call {st.get('call_id')} (supervisor gone); cleaning up")
            stop_capture_processes(cfg, st)
            clear_state(cfg)
        notes += cleanup_processes(cfg, live, scope="all")
    if recover and cfg.records_dir.is_dir():
        for d in sorted(cfg.records_dir.iterdir()):
            if not d.is_dir() or (live and Path(live["call_dir"]) == d):
                continue
            if needs_finalize(d):
                try:
                    meta = finalize(d, keep_raw=bool(cfg.get("audio", "keep_raw_capture", False)), recovered=True)
                    notes.append(f"recovered {d.name}: {meta['duration_s']:.1f} s written to FLAC")
                except Exception as exc:  # report, keep the raw files for another try
                    notes.append(f"could not recover {d.name}: {exc} (raw capture kept)")
    return notes
