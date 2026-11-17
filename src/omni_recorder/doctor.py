"""`omni-rec doctor`: check tools, GPU, config, environment; clean leftovers."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import Config, load_config, project_root

OK, WARN, FAIL = "OK", "WARN", "FAIL"

# tool -> (version args, severity if missing)
TOOLS: dict[str, tuple[list[str], str]] = {
    "ffmpeg": (["-version"], FAIL),
    "ffprobe": (["-version"], FAIL),
    "pw-record": (["--version"], FAIL),
    "pw-dump": (["--version"], WARN),
    "pw-link": (["--version"], WARN),
    "pactl": (["--version"], FAIL),
    "wpctl": (["--version"], WARN),
    "git": (["--version"], WARN),
    "gh": (["--version"], WARN),
    "nvidia-smi": (["--version"], WARN),
}

_VERSION_RE = re.compile(r"\d+\.\d+")


@dataclass
class Check:
    status: str
    name: str
    detail: str


def _run(cmd: list[str], timeout: float = 10.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, str(exc)
    return proc.returncode, (proc.stdout + "\n" + proc.stderr).strip()


def _first_version_line(text: str) -> str | None:
    for line in text.splitlines():
        if _VERSION_RE.search(line):
            return line.strip()[:70]
    return None


def check_tool(name: str, version_args: list[str], missing_status: str) -> Check:
    path = shutil.which(name)
    if not path:
        return Check(missing_status, name, "not found on PATH")
    _, out = _run([path, *version_args])
    return Check(OK, name, _first_version_line(out) or f"present ({path}); version not reported")


def check_gpu() -> list[Check]:
    if not shutil.which("nvidia-smi"):
        return [Check(WARN, "gpu", "nvidia-smi missing; cannot read GPU")]
    code, out = _run(["nvidia-smi", "--query-gpu=name,memory.free,memory.total",
                      "--format=csv,noheader,nounits"])
    if code != 0 or not out.strip():
        return [Check(WARN, "gpu", f"nvidia-smi failed: {out.splitlines()[0] if out else code}")]
    line = out.splitlines()[0]
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 3:
        return [Check(WARN, "gpu", f"unexpected nvidia-smi output: {line}")]
    name, free, total = parts
    return [Check(OK, "gpu", f"{name}, {free} MiB free of {total} MiB")]


def check_python() -> Check:
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    root = project_root()
    venv_ok = Path(sys.prefix).resolve() == (root / ".venv").resolve()
    if not (3, 11) <= (v.major, v.minor) < (3, 14):
        return Check(WARN, "python", f"{ver}: outside supported range 3.11-3.13")
    if not in_venv or not venv_ok:
        return Check(WARN, "python", f"{ver} but not the project .venv ({sys.prefix})")
    return Check(OK, "python", f"{ver} in project .venv")


def check_config() -> tuple[Check, Config | None]:
    try:
        cfg = load_config()
    except (FileNotFoundError, ValueError) as exc:
        return Check(FAIL, "config.toml", str(exc)), None
    return Check(OK, "config.toml", f"loaded {cfg.source}"), cfg


def check_env(root: Path) -> list[Check]:
    expected = {
        "HF_HOME": root / "models" / "hf",
        "XDG_CACHE_HOME": root / ".cache",
        "PIP_CACHE_DIR": root / ".cache" / "pip",
        "TMPDIR": root / ".tmp",
    }
    out: list[Check] = []
    bad = []
    for var, want in expected.items():
        got = os.environ.get(var)
        if not got:
            bad.append(f"{var} unset")
        elif Path(got).resolve() != want.resolve():
            bad.append(f"{var}={got} (expected {want})")
    if bad:
        out.append(Check(WARN, "env vars", "; ".join(bad) + "  -> run: source scripts/env.sh"))
    else:
        out.append(Check(OK, "env vars", "HF_HOME, XDG_CACHE_HOME, PIP_CACHE_DIR, TMPDIR point into the project"))
    if os.environ.get("HF_HUB_OFFLINE") != "1":
        out.append(Check(WARN, "HF_HUB_OFFLINE", f"is {os.environ.get('HF_HUB_OFFLINE')!r}; the app expects 1"))
    return out


def check_models_dir(cfg: Config | None, root: Path) -> Check:
    d = cfg.models_dir if cfg else root / "models"
    if d.is_dir():
        return Check(OK, "models dir", str(d))
    return Check(WARN, "models dir", f"{d} missing (source scripts/env.sh creates it)")


def cleanup_leftovers(cfg: Config | None = None) -> list[Check]:
    """Remove runtime-only objects left by a crashed recording (CLAUDE.md rule 5):
    orphan supervisor / pw-record processes, omni_rec_ PipeWire nodes and their links,
    then convert unfinished raw captures in records/ to FLAC + meta.json."""
    from .recorder import cleanup_leftovers as _cleanup
    if cfg is None:
        return [Check(WARN, "cleanup", "config not loaded; leftovers not checked")]
    try:
        notes = _cleanup(cfg)
    except Exception as exc:  # report, never crash doctor
        return [Check(WARN, "cleanup", f"cleanup failed: {type(exc).__name__}: {exc}")]
    if not notes:
        return [Check(OK, "cleanup", "no leftover recorder processes, PipeWire objects or unfinished captures")]
    out = []
    for n in notes:
        bad = n.startswith("could not")
        out.append(Check(WARN if bad else OK, "cleanup", n))
    return out


def run_checks() -> list[Check]:
    root = project_root()
    checks: list[Check] = []
    for name, (args, sev) in TOOLS.items():
        if name == "nvidia-smi":
            checks.extend(check_gpu())
        else:
            checks.append(check_tool(name, args, sev))
    chrome = shutil.which("google-chrome-stable")
    checks.append(Check(OK if chrome else WARN, "chrome", chrome or "google-chrome-stable not found"))
    checks.append(check_python())
    cfg_check, cfg = check_config()
    checks.append(cfg_check)
    checks.extend(check_env(root))
    checks.append(check_models_dir(cfg, root))
    checks.extend(cleanup_leftovers(cfg))
    return checks


def doctor() -> int:
    checks = run_checks()
    width = max(len(c.name) for c in checks)
    print("omni-rec doctor")
    print("-" * 60)
    for c in checks:
        print(f"{c.status:<5} {c.name:<{width}}  {c.detail}")
    print("-" * 60)
    n = {s: sum(c.status == s for c in checks) for s in (OK, WARN, FAIL)}
    print(f"{n[OK]} OK, {n[WARN]} WARN, {n[FAIL]} FAIL")
    return 1 if n[FAIL] else 0
