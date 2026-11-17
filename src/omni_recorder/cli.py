"""Command-line entry point: omni-rec."""
from __future__ import annotations

import argparse
import sys

from . import __version__
from .calls import STEP_FILES, steps_done
from .config import load_config
from .paths import call_dir, list_call_ids

CONSENT_REMINDER = """\
REMINDER: the other person must know this call is being recorded.
You are responsible for getting their consent, both for recording the call
and for reusing their words or voice later (for example in generated videos).
"""

NOT_IMPLEMENTED_EXIT = 2


def _not_implemented(command: str, stage: int) -> int:
    print(f"omni-rec {command}: not implemented until stage {stage}.", file=sys.stderr)
    return NOT_IMPLEMENTED_EXIT


BANNER = "!" * 72


def _print_warnings(warnings: list[str]) -> None:
    if not warnings:
        return
    print(BANNER)
    print(f"!!  {len(warnings)} WARNING(S) - please read:")
    for w in warnings:
        print(f"!!  - {w}")
    print(BANNER)


def cmd_start(args: argparse.Namespace) -> int:
    print(CONSENT_REMINDER)
    from .recorder import RecorderError, start_recording, status_details
    cfg = load_config()
    try:
        call_id = start_recording(cfg)
    except RecorderError as exc:
        print(f"omni-rec start: {exc}", file=sys.stderr)
        return 1
    d = status_details(cfg)
    print(f"Recording call {call_id}")
    print(f"  folder:      {d.get('call_dir')}")
    print(f"  microphone:  {d.get('mic') or 'NOT FOUND (me.flac will be silent until a microphone appears)'}")
    if d.get("chrome_streams"):
        for c in d["chrome_streams"]:
            print(f"  Chrome:      stream {c.get('serial')} from {c.get('application.name')} ({c.get('application.process.binary')})")
    else:
        print("  Chrome:      no playback stream yet; it is linked automatically as soon as Chrome plays sound")
    print(f"  fallback:    {d.get('monitor_sink') or 'disabled'} monitor (used only if Chrome is never found)")
    print("Stop with: omni-rec stop")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    from .recorder import RecorderError, stop_recording
    import json as _json
    cfg = load_config()
    try:
        call_dir = stop_recording(cfg)
    except RecorderError as exc:
        print(f"omni-rec stop: {exc}", file=sys.stderr)
        return 1
    meta = _json.loads((call_dir / "meta.json").read_text())
    print(f"Stopped. Call {meta['call_id']}: {meta['duration_s']:.1f} s, mode: {meta['them_mode']}")
    for name, f in meta["files"].items():
        stats = f.get("stats") or {}
        extra = f", RMS {stats.get('rms_dbfs')} dBFS, active {100 * stats.get('active_fraction', 0):.1f} %" if stats else ""
        print(f"  {call_dir / name}  ({f['duration_s']:.2f} s{extra})")
    print(f"  {call_dir / 'meta.json'}")
    _print_warnings(meta.get("warnings") or [])
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from .recorder import status_details
    d = status_details(load_config())
    if not d.get("running") and not d.get("stale"):
        print("Not recording.")
        return 0
    if d.get("stale"):
        print(f"NOT running, but call {d['call_id']} was interrupted (crash or reboot). "
              "Run `omni-rec doctor` to clean up and recover its audio.")
        return 3
    m, s = divmod(int(d["elapsed_s"]), 60)
    print(f"Recording call {d['call_id']} for {m} min {s} s (audio written: {d.get('recorded_s')} s)")
    print(f"  them mode now: {d['them_mode_now']}")
    print(f"  microphone:    {d.get('mic')}")
    for c in d.get("chrome_streams") or []:
        print(f"  Chrome stream: {c.get('serial')} {c.get('application.name')} / {c.get('media.name')}")
    print(f"  fallback:      {d.get('monitor_sink')}")
    if d.get("last_error"):
        print(f"  last error:    {d['last_error']}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    cfg = load_config()
    records = cfg.records_dir
    ids = list_call_ids(records)
    if not ids:
        print(f"No calls found in {records}")
        return 0
    steps = list(STEP_FILES)
    print(f"{'call_id':<20} " + " ".join(f"{s:<10}" for s in steps))
    for cid in ids:
        done = steps_done(call_dir(records, cid))
        print(f"{cid:<20} " + " ".join(f"{'yes' if done[s] else '-':<10}" for s in steps))
    return 0


def cmd_process(args: argparse.Namespace) -> int:
    return _not_implemented("process", 3)


def cmd_doctor(args: argparse.Namespace) -> int:
    from .doctor import doctor
    return doctor()


def cmd_watch(args: argparse.Namespace) -> int:
    return _not_implemented("watch", 6)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="omni-rec", description="Local call recorder and script maker (fully offline).")
    p.add_argument("--version", action="version", version=f"omni-rec {__version__}")
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    sub.add_parser("start", help="begin recording (prints consent reminder)").set_defaults(func=cmd_start)
    sub.add_parser("stop", help="stop recording and finalize files").set_defaults(func=cmd_stop)
    sub.add_parser("status", help="is a recording running?").set_defaults(func=cmd_status)
    sub.add_parser("list", help="list calls and which steps are done").set_defaults(func=cmd_list)

    pr = sub.add_parser("process", help="transcribe + translate to English + notes")
    pr.add_argument("call_id")
    pr.add_argument("--no-translate", action="store_true", help="skip the English translation file")
    pr.add_argument("--highlights", action="store_true", help="also pick and cut interesting parts")
    pr.add_argument("--brief", action="store_true", help="also write the video brief")
    pr.add_argument("--all", action="store_true", help="everything")
    pr.set_defaults(func=cmd_process)

    sub.add_parser("doctor", help="check tools, GPU, models; clean leftovers").set_defaults(func=cmd_doctor)
    sub.add_parser("watch", help="(stage 6, optional) auto start/stop on a Chrome call").set_defaults(func=cmd_watch)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (FileNotFoundError, ValueError) as exc:
        print(f"omni-rec: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
