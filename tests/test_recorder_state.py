"""State-file handling: stale / corrupt state, PID reuse protection, status. No audio server needed."""
import json
import os
import subprocess
import sys
import time

import pytest

from omni_recorder import recorder
from omni_recorder.config import load_config


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    c = tmp_path / "config.toml"
    c.write_text("\n".join(f"[{s}]" for s in ("audio", "languages", "speech", "translation", "llm"))
                 + f'\n[paths]\nrecords_dir = "{tmp_path / "records"}"\nruntime_dir = "{tmp_path / "rt"}"\n')
    monkeypatch.setenv("OMNI_CONFIG", str(c))
    return load_config()


def _write_state(cfg, **kw):
    st = {"call_id": "2026-01-01_0000", "call_dir": "/nonexistent", "daemon_pid": 1,
          "daemon_starttime": 0, "boot_id": recorder.boot_id(), "node_name": "omni_rec_capture_x",
          "started_wall": time.time() - 65}
    st.update(kw)
    (recorder.runtime_dir(cfg) / "state.json").write_text(json.dumps(st))
    return st


def test_no_state_means_not_recording(cfg):
    assert recorder.load_state(cfg) is None
    assert recorder.recording_status(cfg) is None
    assert recorder.status_details(cfg) == {"running": False}


def test_corrupt_state_is_not_alive(cfg):
    (recorder.runtime_dir(cfg) / "state.json").write_text("{not json")
    st = recorder.load_state(cfg)
    assert st == {"corrupt": True} and not recorder.daemon_alive(st)


def test_reused_pid_is_not_ours(cfg):
    # our own pytest process is alive, but its command line is not the supervisor
    st = _write_state(cfg, daemon_pid=os.getpid(), daemon_starttime=recorder.proc_starttime(os.getpid()))
    assert recorder.daemon_alive(st) is False
    d = recorder.status_details(cfg)
    assert d["running"] is False and d["stale"] is True and d["call_id"] == "2026-01-01_0000"


def test_daemon_argv_must_be_exact():
    py = sys.executable
    assert recorder.is_daemon_argv([py, "-m", "omni_recorder.capture_daemon", "/x", "--runtime-dir", "/y"])
    # a shell or editor whose command text merely mentions the module is not the daemon
    assert not recorder.is_daemon_argv(["/usr/bin/bash", "-c", "python -m omni_recorder.capture_daemon"])
    assert not recorder.is_daemon_argv([py, "-c", "pass", "omni_recorder.capture_daemon"])
    assert not recorder.is_daemon_argv([])


def test_find_procs_matches_program_not_text():
    marker = "omni_rec_test_find_procs_marker"
    sh = subprocess.Popen(["sh", "-c", f"sleep 30; echo pw-loopback {marker}"])
    try:
        time.sleep(0.2)
        assert recorder.find_procs("pw-loopback", marker) == []      # the shell only mentions it
        assert [pid for pid, _ in recorder.find_procs("sh", marker)] == [sh.pid]
    finally:
        sh.kill()
        sh.wait()


def test_wrong_starttime_or_boot_is_stale(cfg, monkeypatch):
    monkeypatch.setattr(recorder, "is_daemon_argv", lambda argv: True)   # stand-in for the real daemon
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        good = recorder.proc_starttime(p.pid)
        st = _write_state(cfg, daemon_pid=p.pid, daemon_starttime=good)
        assert recorder.daemon_alive(st) is True
        assert recorder.daemon_alive({**st, "daemon_starttime": good + 1}) is False
        assert recorder.daemon_alive({**st, "boot_id": "another-boot"}) is False
    finally:
        p.kill()
        p.wait()
    assert recorder.daemon_alive(st) is False                # dead (and reaped) process


def test_zombie_counts_as_dead():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    time.sleep(0.5)                                           # exited, not yet reaped -> zombie
    assert recorder.proc_starttime(p.pid) is None
    p.wait()


def test_stop_without_recording_raises(cfg):
    with pytest.raises(recorder.RecorderError, match="no recording is running"):
        recorder.stop_recording(cfg)


def test_stop_clears_corrupt_state(cfg):
    (recorder.runtime_dir(cfg) / "state.json").write_text("garbage")
    with pytest.raises(recorder.RecorderError):
        recorder.stop_recording(cfg)
    assert recorder.load_state(cfg) is None


def test_signal_and_wait_on_child():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    import signal
    import threading
    threading.Thread(target=p.wait, daemon=True).start()     # reap so it does not stay a zombie
    assert recorder.stop_process(p.pid, signal.SIGINT, 5).startswith("stopped")


def test_quoted_node_name_is_exact():
    q = recorder._quoted("omni_rec_capture_2026_11_17_1450")
    assert q in 'node.name = "omni_rec_capture_2026_11_17_1450" x'
    assert q not in 'node.name = "omni_rec_capture_2026_11_17_1450_2" x'


def test_orphaned_detection():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert recorder.orphaned(child.pid) is False          # parent (pytest) is alive
    finally:
        child.kill()
        child.wait()
    out = subprocess.run(["sh", "-c", "sleep 5 >/dev/null 2>&1 & echo $!"], capture_output=True, text=True)
    pid = int(out.stdout.strip())
    time.sleep(0.3)                                            # sh has exited: sleep is adopted
    try:
        assert recorder.orphaned(pid) is True
    finally:
        os.kill(pid, 9)
