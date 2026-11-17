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


def cmd_start(args: argparse.Namespace) -> int:
    print(CONSENT_REMINDER)
    return _not_implemented("start (recording)", 2)


def cmd_stop(args: argparse.Namespace) -> int:
    return _not_implemented("stop", 2)


def cmd_status(args: argparse.Namespace) -> int:
    return _not_implemented("status", 2)


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
