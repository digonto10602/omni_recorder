"""`omni-rec manual` and `omni-rec keys`: show the user manual and the cheat sheet.

The cheat-sheet text lives in ONE file, docs/CHEATSHEET.md. The manual embeds the same
text verbatim (a test checks this), and the desktop popup runs `omni-rec keys`, so the
three can never disagree.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from .config import Config, project_root

CHEATSHEET_NAME = "CHEATSHEET.md"
MANUAL_NAME = "MANUAL.md"


def docs_dir() -> Path:
    """docs/ next to the package (editable install), else under the project root."""
    here = Path(__file__).resolve().parents[2] / "docs"
    return here if here.is_dir() else project_root() / "docs"


def manual_path() -> Path:
    return docs_dir() / MANUAL_NAME


def cheatsheet_path() -> Path:
    return docs_dir() / CHEATSHEET_NAME


def cheatsheet_text() -> str:
    return cheatsheet_path().read_text(encoding="utf-8")


def status_line(cfg: Config) -> str:
    """One line: recording or not, call id, elapsed time. Never raises."""
    try:
        from .recorder import status_details
        d = status_details(cfg)
    except Exception as exc:  # the cheat sheet must always show, even if status cannot be read
        return f"Status: unknown ({type(exc).__name__}: {exc})"
    if d.get("stale"):
        return f"Status: INTERRUPTED call {d.get('call_id')} (crash or reboot) - run: omni-rec doctor"
    if not d.get("running"):
        return "Status: not recording"
    m, s = divmod(int(d.get("elapsed_s") or 0), 60)
    return f"Status: RECORDING call {d.get('call_id')} for {m} min {s} s"


def show_manual() -> int:
    path = manual_path()
    if not path.is_file():
        print(f"omni-rec manual: {path} not found", file=sys.stderr)
        return 1
    text = path.read_text(encoding="utf-8")
    pager = shutil.which("less")
    if sys.stdout.isatty() and pager:
        try:
            subprocess.run([pager, "-R", str(path)], check=False)
            return 0
        except OSError:
            pass
    sys.stdout.write(text)
    return 0


def show_keys(cfg: Config) -> int:
    path = cheatsheet_path()
    if not path.is_file():
        print(f"omni-rec keys: {path} not found", file=sys.stderr)
        return 1
    print(status_line(cfg))
    print()
    sys.stdout.write(cheatsheet_text())
    return 0
