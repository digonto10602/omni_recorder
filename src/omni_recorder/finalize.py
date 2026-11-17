"""Turn a raw capture folder into me.flac, them.flac, mix.flac and meta.json.

Used by `omni-rec stop` and by `omni-rec doctor` (crash recovery). It is safe to
run again on the same folder: outputs are written to *.part files and renamed only
after they are verified, and the raw capture is removed only after that.

Raw capture layout (written by capture_daemon):
  capture.json          format, channel layout, list of segments (one per recorder process)
  capture_NNN.f32       raw little-endian 32-bit float frames, 6 interleaved channels
  events.jsonl          one JSON object per line: links made/lost, streams seen, errors
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from . import __version__
from .audiocheck import BleedDetector, TrackStats, sanity_warnings

FRAME_CHUNK = 48000          # frames per processing chunk (1 s at 48 kHz)
MIX_PEAK_TARGET = 10 ** (-1.0 / 20)   # mix is scaled down (never up) to peak at most -1 dBFS
CAPTURE_JSON = "capture.json"
EVENTS = "events.jsonl"
META = "meta.json"


# ---- small io helpers --------------------------------------------------------------

def write_json_atomic(path: Path, data: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w") as fh:
        json.dump(data, fh, indent=2, default=str)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def read_events(call_dir: Path) -> list[dict]:
    p = call_dir / EVENTS
    if not p.exists():
        return []
    out = []
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"event": "unreadable_event_line"})   # e.g. half-written line after a crash
    return out


def iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, timezone.utc).astimezone().isoformat(timespec="milliseconds") if ts else None


# ---- timeline ----------------------------------------------------------------------

def segment_frames(path: Path, channels: int) -> int:
    """Whole frames in a raw segment (a partial last frame after a crash is ignored)."""
    return path.stat().st_size // (4 * channels) if path.exists() else 0


def build_timeline(segments: list[dict], frames: list[int], rate: int) -> list[dict]:
    """Place each segment on one shared timeline.

    Segment 0 starts at frame 0. A later segment (the recorder was restarted, e.g.
    after the audio server restarted) starts at its measured start time relative to
    segment 0, but never before the previous segment ends. The space between is a
    gap that is filled with silence so the timeline keeps real time.
    Returns [{"index", "offset", "frames", "gap_before"}] in frames.
    """
    out: list[dict] = []
    t0 = None
    end = 0
    for i, (seg, n) in enumerate(zip(segments, frames)):
        start = seg.get("start_mono")
        if t0 is None:
            t0 = start
            off = 0
        elif start is None or t0 is None:
            off = end
        else:
            off = max(end, int(round((start - t0) * rate)))
        out.append({"index": i, "offset": off, "frames": n, "gap_before": off - end})
        end = off + n
    return out


def iter_frames(call_dir: Path, segments: list[dict], timeline: list[dict], channels: int,
                chunk: int = FRAME_CHUNK) -> Iterator[np.ndarray]:
    """Yield (n, channels) float32 arrays covering the whole timeline, gaps as zeros."""
    for seg, tl in zip(segments, timeline):
        gap = tl["gap_before"]
        while gap > 0:
            n = min(gap, chunk)
            yield np.zeros((n, channels), dtype=np.float32)
            gap -= n
        left = tl["frames"]
        path = call_dir / seg["file"]
        if left <= 0 or not path.exists():
            continue
        with path.open("rb") as fh:
            while left > 0:
                n = min(left, chunk)
                buf = fh.read(n * channels * 4)
                got = len(buf) // (channels * 4)
                if got == 0:
                    break
                yield np.frombuffer(buf[: got * channels * 4], dtype="<f4").reshape(got, channels)
                left -= got


# ---- event summary -----------------------------------------------------------------

def summarize_events(events: list[dict], total_s: float) -> dict:
    """Which capture targets were used, and how long Chrome had a linked stream."""
    mic_nodes: dict[str, dict] = {}
    sinks: dict[str, dict] = {}
    chrome: dict[str, dict] = {}
    open_since: dict[str, float] = {}
    for e in events:
        ev = e.get("event")
        pos = float(e.get("pos_s") or 0.0)
        node = e.get("node") or {}
        if ev == "mic_linked":
            mic_nodes.setdefault(str(node.get("node.name")), {**node, "first_pos_s": pos})
        elif ev == "monitor_linked":
            sinks.setdefault(str(node.get("node.name")), {**node, "first_pos_s": pos})
        elif ev == "chrome_stream_linked":
            key = str(node.get("serial"))
            c = chrome.setdefault(key, {**node, "intervals": []})
            open_since[key] = pos
        elif ev == "chrome_stream_gone":
            key = str(node.get("serial"))
            if key in open_since:
                chrome[key]["intervals"].append([round(open_since.pop(key), 3), round(pos, 3)])
    for key, start in open_since.items():
        chrome[key]["intervals"].append([round(start, 3), round(total_s, 3)])
    # union of intervals = time with at least one Chrome stream linked
    iv = sorted(i for c in chrome.values() for i in c["intervals"])
    covered = 0.0
    cur_s = cur_e = None
    for s, e in iv:
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                covered += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        covered += cur_e - cur_s
    return {"mic_nodes": list(mic_nodes.values()), "monitor_sinks": list(sinks.values()),
            "chrome_streams": list(chrome.values()), "chrome_linked_s": round(covered, 3)}


# ---- tools -------------------------------------------------------------------------

def tool_versions() -> dict[str, str]:
    out = {}
    for name, args in (("pw-record", ["--version"]), ("ffmpeg", ["-version"])):
        try:
            p = subprocess.run([name, *args], capture_output=True, text=True, timeout=10)
            out[name] = " | ".join(l.strip() for l in p.stdout.splitlines()[:3] if l.strip())[:200]
        except (OSError, subprocess.SubprocessError) as exc:
            out[name] = f"unavailable: {exc}"
    return out


def flac_frames(path: Path) -> tuple[int, int, int]:
    """(total samples, sample rate, channels) from a FLAC file's header via ffprobe."""
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                        "stream=duration_ts,sample_rate,channels", "-of", "json", str(path)],
                       capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path.name}: {p.stderr.strip()[:200]}")
    s = json.loads(p.stdout)["streams"][0]
    return int(s["duration_ts"]), int(s["sample_rate"]), int(s["channels"])


# ---- main entry --------------------------------------------------------------------

def finalize(call_dir: Path, keep_raw: bool = False, recovered: bool = False,
             stop_info: dict | None = None) -> dict:
    """Write the FLAC files and meta.json. Returns the meta dict. Raises on failure
    (the raw capture is then left untouched so it can be retried)."""
    call_dir = Path(call_dir)
    cap = json.loads((call_dir / CAPTURE_JSON).read_text())
    rate, ch = int(cap["rate"]), int(cap["channels"])
    layout = {k: list(v) for k, v in cap["layout"].items()}
    segments = cap.get("segments") or []
    frames = [segment_frames(call_dir / s["file"], ch) for s in segments]
    timeline = build_timeline(segments, frames, rate)
    total = (timeline[-1]["offset"] + timeline[-1]["frames"]) if timeline else 0
    total_s = total / rate
    if total == 0:
        raise RuntimeError(f"no audio was captured in {call_dir} (capture files empty or missing)")

    events = read_events(call_dir)
    summary = summarize_events(events, total_s)
    system_recorded = bool(cap.get("system_monitor_enabled", True))
    if summary["chrome_streams"]:
        mode, them_role = "chrome-only", "chrome"
        mode_reason = f"{len(summary['chrome_streams'])} Chrome playback stream(s) were linked directly"
    elif system_recorded:
        mode, them_role = "fallback-system-monitor", "system"
        mode_reason = ("no Chrome playback stream appeared during the recording; them.flac is the default "
                       "output's monitor, i.e. ALL system sound")
    else:
        mode, them_role = "chrome-only", "chrome"
        mode_reason = "no Chrome stream appeared and the system-monitor fallback is disabled in config.toml"

    def mono(block: np.ndarray, role: str) -> np.ndarray:
        a, b = layout[role]
        return 0.5 * (block[:, a].astype(np.float64) + block[:, b].astype(np.float64))

    # ---- pass 1: statistics ----------------------------------------------------
    st = {r: TrackStats(rate) for r in ("me", "chrome", "system")}
    bleed = BleedDetector(rate)
    peak_sum = 0.0
    for block in iter_frames(call_dir, segments, timeline, ch):
        tracks = {r: mono(block, r) for r in st}
        for r, x in tracks.items():
            st[r].add(x, raw_channels=np.max(np.abs(block[:, layout[r]]), axis=1))  # clipped frames
        s = tracks["me"] + tracks[them_role]
        if s.size:
            peak_sum = max(peak_sum, float(np.max(np.abs(s))))
        bleed.add(tracks["me"], tracks[them_role])
    stats = {r: v.result() for r, v in st.items()}
    mix_gain = min(1.0, MIX_PEAK_TARGET / peak_sum) if peak_sum > 0 else 1.0

    warnings: list[str] = []
    write_system_copy = False
    if mode == "fallback-system-monitor":
        warnings.append("FALLBACK: Chrome's own audio stream was never found, so them.flac holds ALL sound the "
                        "computer played (notifications, music, other tabs), not only the call.")
    if mode == "chrome-only" and system_recorded:
        ch_silent = stats["chrome"]["active_fraction"] < 0.005
        sys_active = stats["system"]["active_fraction"] >= 0.005
        if ch_silent and sys_active:
            write_system_copy = True
            warnings.append("CHROME SILENT: the linked Chrome stream(s) carried no sound, but the computer did play "
                            "sound. A copy of all system sound was saved as them_system.flac; check it.")
        gap = total_s - summary["chrome_linked_s"]
        if total_s >= 30 and gap > max(10.0, 0.1 * total_s):
            warnings.append(f"CHROME ABSENT: no Chrome stream was linked for {gap:.1f} s of the {total_s:.1f} s "
                            "recording (before the call started, or while it reconnected). Sound from that time "
                            "is not in them.flac.")
    warnings += sanity_warnings(stats["me"], stats[them_role], total_s)
    b = bleed.result()
    if b["detected"]:
        warnings.append(f"BLEED: your microphone picks up the other side from the speakers (delay about "
                        f"{b['lag_ms']} ms). Headphones give much cleaner separation of the two voices.")
    for e in events:
        if e.get("event") in ("capture_process_died", "link_failed", "daemon_error", "mic_missing"):
            warnings.append(f"EVENT {e.get('event')} at {e.get('pos_s')} s: {e.get('detail', '')}".strip())

    # ---- pass 2: encode ----------------------------------------------------------
    them_a, them_b = layout[them_role]
    me_a, me_b = layout["me"]
    g = 0.5 * mix_gain
    outputs = {"me.flac": f"pan=mono|c0=0.5*c{me_a}+0.5*c{me_b}",
               "them.flac": f"pan=mono|c0=0.5*c{them_a}+0.5*c{them_b}",
               "mix.flac": f"pan=mono|c0={g:.9f}*c{me_a}+{g:.9f}*c{me_b}+{g:.9f}*c{them_a}+{g:.9f}*c{them_b}"}
    if write_system_copy:
        sa, sb = layout["system"]
        outputs["them_system.flac"] = f"pan=mono|c0=0.5*c{sa}+0.5*c{sb}"
    labels = [f"o{i}" for i in range(len(outputs))]
    fc = f"[0:a]asplit={len(outputs)}" + "".join(f"[s{i}]" for i in range(len(outputs))) + ";"
    fc += ";".join(f"[s{i}]{flt}[{labels[i]}]" for i, flt in enumerate(outputs.values()))
    cmd = ["ffmpeg", "-hide_banner", "-y", "-loglevel", "error", "-nostats",
           "-f", "f32le", "-ar", str(rate), "-ac", str(ch), "-i", "pipe:0", "-filter_complex", fc]
    for lab, name in zip(labels, outputs):
        cmd += ["-map", f"[{lab}]", "-c:a", "flac", "-sample_fmt", "s32", "-bits_per_raw_sample", "24",
                "-ar", str(rate), "-f", "flac", str(call_dir / (name + ".part"))]
    log_path = call_dir / "ffmpeg_finalize.log"
    with log_path.open("w") as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=log)
        assert proc.stdin is not None
        try:
            for block in iter_frames(call_dir, segments, timeline, ch):
                proc.stdin.write(np.ascontiguousarray(block, dtype="<f4").tobytes())
            proc.stdin.close()
        except BrokenPipeError:
            pass
        rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg failed (exit {rc}); see {log_path}")

    files: dict[str, dict] = {}
    for name in outputs:
        part = call_dir / (name + ".part")
        n, r, c = flac_frames(part)
        if n != total or r != rate or c != 1:
            raise RuntimeError(f"{name}: wrote {n} samples at {r} Hz, {c} ch; expected {total} at {rate} Hz mono")
        files[name] = {"samples": n, "duration_s": round(n / r, 6), "channels": c}
    for name in outputs:
        os.replace(call_dir / (name + ".part"), call_dir / name)
    if log_path.exists() and log_path.stat().st_size == 0:
        log_path.unlink()

    # ---- meta.json ---------------------------------------------------------------
    seg0 = segments[0] if segments else {}
    start_wall = seg0.get("start_wall")
    me_s, them_s = files["me.flac"], files["them.flac"]
    meta = {
        "schema": 1,
        "app_version": __version__,
        "call_id": call_dir.name,
        "start_wall": iso(start_wall),
        "end_wall": iso(start_wall + total_s) if start_wall else None,
        "start_wall_unix": start_wall,
        "start_monotonic_s": seg0.get("start_mono"),
        "start_time_uncertainty_s": seg0.get("start_uncertainty_s"),
        "duration_s": round(total_s, 6),
        "sample_rate": rate,
        "files": {k: {**v, **({"stats": stats["me"]} if k == "me.flac" else {}),
                      **({"stats": stats[them_role]} if k == "them.flac" else {}),
                      **({"stats": stats["system"]} if k == "them_system.flac" else {}),
                      **({"gain_applied": round(mix_gain, 6),
                          "description": "mono: (me + them) x gain; gain only ever lowers the level to avoid clipping"}
                         if k == "mix.flac" else {})}
                  for k, v in files.items()},
        "them_mode": mode,
        "them_mode_reason": mode_reason,
        "capture": {
            "method": cap.get("method"),
            "recorder_node": cap.get("node_name"),
            "raw_format": f"{cap['format']}, {ch} channels, {rate} Hz",
            "channel_layout": layout,
            "config": cap.get("config", {}),
            "mic_nodes_used": summary["mic_nodes"],
            "chrome_streams": summary["chrome_streams"],
            "chrome_linked_s": summary["chrome_linked_s"],
            "monitor_sinks_used": summary["monitor_sinks"],
            "all_tracks_stats": stats,
        },
        "alignment": {
            "shared_clock": True,
            "explanation": ("me and them are channels of ONE PipeWire capture node, so sample i of me.flac "
                            "and sample i of them.flac were captured in the same audio cycle; no trim or pad "
                            "is needed and they cannot drift apart."),
            "track_start_offset_ms": 0.0,
            "trim_or_pad_applied_ms": 0.0,
            "length_difference_ms": round(1000 * (me_s["samples"] - them_s["samples"]) / rate, 3),
            "tracks": {t: {"start_wall": iso(start_wall), "start_monotonic_s": seg0.get("start_mono"),
                           "first_sample_index": 0} for t in ("me", "them")},
        },
        "segments": [{**s, **t} for s, t in zip(segments, timeline)],
        "bleed_check": b,
        "warnings": warnings,
        "events": events,
        "tools": cap.get("tools") or tool_versions(),
        "recovered_after_crash": recovered,
        "stop": stop_info or {},
        "finalized_wall": iso(datetime.now().timestamp()),
    }
    write_json_atomic(call_dir / META, meta)

    if not keep_raw:
        for s in segments:
            p = call_dir / s["file"]
            if p.exists():
                p.unlink()
    return meta


def needs_finalize(call_dir: Path) -> bool:
    """A folder holds an unfinished recording: raw capture present, no meta.json."""
    return (call_dir / CAPTURE_JSON).exists() and not (call_dir / META).exists() and \
        any(call_dir.glob("capture_*.f32"))
