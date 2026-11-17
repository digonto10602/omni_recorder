"""Timeline/alignment math, statistics, bleed detection and meta.json, on synthetic audio only."""
import json
import math
from pathlib import Path

import numpy as np
import pytest

from omni_recorder import audiocheck, finalize
from omni_recorder.capture_daemon import LAYOUT

RATE = 48000
SEED = 12345


# ---- timeline ------------------------------------------------------------------------

def test_timeline_single_segment():
    tl = finalize.build_timeline([{"start_mono": 100.0}], [48000], RATE)
    assert tl == [{"index": 0, "offset": 0, "frames": 48000, "gap_before": 0}]


def test_timeline_gap_is_padded():
    # segment 0: 1 s of audio; segment 1 starts 3 s after segment 0 -> 2 s of silence between
    segs = [{"start_mono": 10.0}, {"start_mono": 13.0}]
    tl = finalize.build_timeline(segs, [RATE, RATE], RATE)
    assert tl[1]["offset"] == 3 * RATE and tl[1]["gap_before"] == 2 * RATE


def test_timeline_never_overlaps():
    # start estimate slightly too early must not overlap the previous segment
    segs = [{"start_mono": 10.0}, {"start_mono": 10.5}]
    tl = finalize.build_timeline(segs, [RATE, RATE], RATE)
    assert tl[1]["offset"] == RATE and tl[1]["gap_before"] == 0


def test_iter_frames_concatenates_with_silence(tmp_path):
    ch = 6
    a = np.ones((10, ch), dtype="<f4")
    b = 2 * np.ones((5, ch), dtype="<f4")
    (tmp_path / "s0.f32").write_bytes(a.tobytes())
    (tmp_path / "s1.f32").write_bytes(b.tobytes() + b"\x00\x01")   # partial frame from a crash
    segs = [{"file": "s0.f32"}, {"file": "s1.f32"}]
    frames = [finalize.segment_frames(tmp_path / s["file"], ch) for s in segs]
    assert frames == [10, 5]
    tl = [{"offset": 0, "frames": 10, "gap_before": 0}, {"offset": 13, "frames": 5, "gap_before": 3}]
    out = np.concatenate(list(finalize.iter_frames(tmp_path, segs, tl, ch, chunk=4)))
    assert out.shape == (18, ch)
    assert (out[:10] == 1).all() and (out[10:13] == 0).all() and (out[13:] == 2).all()


# ---- statistics -------------------------------------------------------------------------

def test_track_stats_tone_levels():
    t = np.arange(RATE * 2) / RATE
    x = 0.5 * np.sin(2 * math.pi * 1000 * t)
    s = audiocheck.TrackStats(RATE)
    for i in range(0, x.size, 7000):        # odd chunk size exercises the window carry
        s.add(x[i:i + 7000])
    r = s.result()
    assert r["peak_dbfs"] == pytest.approx(20 * math.log10(0.5), abs=0.01)
    assert r["rms_dbfs"] == pytest.approx(20 * math.log10(0.5 / math.sqrt(2)), abs=0.01)
    assert r["active_fraction"] == 1.0 and r["clipped_samples"] == 0
    assert r["active_first_s"] == 0.0 and r["active_last_s"] == pytest.approx(2.0)


def test_track_stats_silence_and_clipping():
    s = audiocheck.TrackStats(RATE)
    s.add(np.zeros(RATE))
    assert s.result()["active_fraction"] == 0.0 and s.result()["rms_dbfs"] is None
    c = audiocheck.TrackStats(RATE)
    c.add(np.clip(1.5 * np.sin(np.linspace(0, 200, RATE)), -1, 1))
    assert c.result()["clipped_samples"] > audiocheck.CLIP_WARN_SAMPLES


def _stats(active_fraction=0.5, clipped=0, span=100.0, rms=-20.0):
    return {"active_fraction": active_fraction, "clipped_samples": clipped, "active_span_s": span,
            "rms_dbfs": rms, "peak_dbfs": rms + 3}


def test_sanity_warnings():
    assert audiocheck.sanity_warnings(_stats(), _stats(), 120) == []
    w = audiocheck.sanity_warnings(_stats(active_fraction=0.0), _stats(), 120)
    assert len(w) == 1 and w[0].startswith("SILENT") and "me.flac" in w[0]
    w = audiocheck.sanity_warnings(_stats(), _stats(clipped=5000), 120)
    assert len(w) == 1 and w[0].startswith("CLIPPED") and "them.flac" in w[0]
    w = audiocheck.sanity_warnings(_stats(span=100), _stats(span=20), 120)
    assert len(w) == 1 and w[0].startswith("SHORT") and "them.flac" in w[0]


# ---- bleed --------------------------------------------------------------------------------

def _speechlike(rng, n):
    """Noise shaped into 200-ms syllable bursts (synthetic, not speech)."""
    x = rng.standard_normal(n)
    env = (np.sin(2 * math.pi * 2.5 * np.arange(n) / RATE) > -0.2).astype(float)
    return 0.1 * x * env


def _run_bleed(me, them, chunk=RATE // 2):
    d = audiocheck.BleedDetector(RATE)
    for i in range(0, me.size, chunk):
        d.add(me[i:i + chunk], them[i:i + chunk])
    return d.result()


def test_bleed_detected_with_delay():
    rng = np.random.default_rng(SEED)
    n = RATE * 30
    them = _speechlike(rng, n)
    delay = int(0.060 * RATE)
    me = 0.3 * np.concatenate([np.zeros(delay), them[:-delay]]) + 0.01 * rng.standard_normal(n)
    r = _run_bleed(me, them)
    assert r["detected"] is True
    assert r["lag_ms"] == pytest.approx(60.0, abs=1.0)


def test_no_bleed_for_independent_signals():
    rng = np.random.default_rng(SEED + 1)
    n = RATE * 30
    r = _run_bleed(_speechlike(rng, n), _speechlike(rng, n))
    assert r["detected"] is False
    assert r["blocks_judged"] >= audiocheck.BLEED_MIN_BLOCKS


def test_bleed_needs_audible_other_side():
    rng = np.random.default_rng(SEED + 2)
    n = RATE * 10
    r = _run_bleed(_speechlike(rng, n), np.zeros(n))
    assert r["detected"] is False and r["blocks_judged"] == 0


# ---- events / meta --------------------------------------------------------------------------

def test_summarize_events_chrome_churn():
    c1 = {"serial": 1, "application.name": "Google Chrome"}
    c2 = {"serial": 2, "application.name": "Google Chrome"}
    ev = [{"event": "mic_linked", "pos_s": 0.0, "node": {"node.name": "mic"}},
          {"event": "chrome_stream_linked", "pos_s": 5.0, "node": c1},
          {"event": "chrome_stream_gone", "pos_s": 20.0, "node": c1},
          {"event": "chrome_stream_linked", "pos_s": 22.0, "node": c2},
          {"event": "chrome_stream_linked", "pos_s": 30.0, "node": {"serial": 3}}]
    s = finalize.summarize_events(ev, total_s=60.0)
    assert [c["intervals"] for c in s["chrome_streams"]] == [[[5.0, 20.0]], [[22.0, 60.0]], [[30.0, 60.0]]]
    assert s["chrome_linked_s"] == pytest.approx(15.0 + 38.0)
    assert s["mic_nodes"][0]["node.name"] == "mic"


def _make_capture(d: Path, me_sig, chrome_sig, system_sig, chrome_event=True):
    n = me_sig.size
    frames = np.zeros((n, 6), dtype="<f4")
    frames[:, 0] = frames[:, 1] = me_sig
    frames[:, 2] = frames[:, 3] = chrome_sig
    frames[:, 4] = frames[:, 5] = system_sig
    (d / "capture_000.f32").write_bytes(frames.tobytes())
    cap = {"format": "f32le", "rate": RATE, "channels": 6, "layout": LAYOUT, "node_name": "omni_rec_capture_x",
           "method": "test", "system_monitor_enabled": True, "tools": {"test": "synthetic"},
           "segments": [{"file": "capture_000.f32", "start_mono": 1000.0, "start_wall": 1_700_000_000.0,
                         "start_uncertainty_s": 0.005}]}
    (d / "capture.json").write_text(json.dumps(cap))
    ev = [{"event": "mic_linked", "pos_s": 0.0, "node": {"node.name": "synthetic_mic"}}]
    if chrome_event:
        ev.append({"event": "chrome_stream_linked", "pos_s": 0.0,
                   "node": {"serial": 7, "application.name": "Google Chrome"}})
    (d / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in ev) + '{"event": "half-writ')


def _tone(f, secs, amp=0.25):
    t = np.arange(int(RATE * secs)) / RATE
    return amp * np.sin(2 * math.pi * f * t)


def test_finalize_end_to_end(tmp_path):
    secs = 3.0
    me, ch, sy = _tone(440, secs), _tone(1000, secs), _tone(1000, secs) + _tone(3000, secs, 0.1)
    _make_capture(tmp_path, me, ch, sy)
    meta = finalize.finalize(tmp_path)
    assert meta["them_mode"] == "chrome-only"
    assert meta["duration_s"] == pytest.approx(secs)
    assert meta["alignment"]["length_difference_ms"] == 0.0
    for f in ("me.flac", "them.flac", "mix.flac"):
        assert (tmp_path / f).exists()
        assert meta["files"][f]["samples"] == int(RATE * secs)
    assert not (tmp_path / "capture_000.f32").exists()          # raw removed after verification
    assert not list(tmp_path.glob("*.part"))
    assert "unreadable_event_line" in [e["event"] for e in meta["events"]]
    on_disk = json.loads((tmp_path / "meta.json").read_text())
    assert on_disk["call_id"] == tmp_path.name and on_disk["sample_rate"] == RATE
    assert on_disk["files"]["me.flac"]["stats"]["rms_dbfs"] == pytest.approx(20 * math.log10(0.25 / math.sqrt(2)), abs=0.05)
    assert on_disk["files"]["mix.flac"]["gain_applied"] <= 1.0
    assert not finalize.needs_finalize(tmp_path)


def test_finalize_fallback_mode_and_silence_warning(tmp_path):
    secs = 3.0
    _make_capture(tmp_path, np.zeros(int(RATE * secs)), np.zeros(int(RATE * secs)), _tone(1000, secs),
                  chrome_event=False)
    meta = finalize.finalize(tmp_path, keep_raw=True)
    assert meta["them_mode"] == "fallback-system-monitor"
    assert any(w.startswith("FALLBACK") for w in meta["warnings"])
    assert any(w.startswith("SILENT") and "me.flac" in w for w in meta["warnings"])
    assert (tmp_path / "capture_000.f32").exists()


def test_finalize_chrome_silent_saves_system_copy(tmp_path):
    secs = 3.0
    _make_capture(tmp_path, _tone(440, secs), np.zeros(int(RATE * secs)), _tone(1000, secs))
    meta = finalize.finalize(tmp_path)
    assert meta["them_mode"] == "chrome-only"
    assert (tmp_path / "them_system.flac").exists()
    assert any(w.startswith("CHROME SILENT") for w in meta["warnings"])


def test_needs_finalize(tmp_path):
    assert not finalize.needs_finalize(tmp_path)
    (tmp_path / "capture.json").write_text("{}")
    (tmp_path / "capture_000.f32").write_bytes(b"")
    assert finalize.needs_finalize(tmp_path)
