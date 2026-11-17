import os
import subprocess
import sys
from pathlib import Path

import pytest

from omni_recorder.cli import CONSENT_REMINDER, main

ROOT = Path(__file__).resolve().parents[1]


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    for cmd in ("start", "stop", "status", "list", "process", "doctor", "watch"):
        assert cmd in out


def test_process_flags_parse():
    from omni_recorder.cli import build_parser
    a = build_parser().parse_args(["process", "x", "--no-translate", "--highlights", "--brief", "--all"])
    assert a.call_id == "x" and a.no_translate and a.highlights and a.brief and a.all


def test_start_prints_consent_and_exits_2(capsys):
    assert main(["start"]) == 2
    cap = capsys.readouterr()
    assert "other person must know" in cap.out
    assert CONSENT_REMINDER.strip().splitlines()[0] in cap.out
    assert "stage 2" in cap.err


@pytest.mark.parametrize("cmd,stage", [(["stop"], "2"), (["status"], "2"), (["process", "x"], "3"), (["watch"], "6")])
def test_unbuilt_commands_exit_2(cmd, stage, capsys):
    assert main(cmd) == 2
    assert f"stage {stage}" in capsys.readouterr().err


def test_list_shows_steps(tmp_path, monkeypatch, capsys):
    rec = tmp_path / "records" / "2026-01-01_0000"
    rec.mkdir(parents=True)
    for f in ("me.flac", "them.flac", "meta.json", "transcript.json", "transcript.md"):
        (rec / f).write_bytes(b"")
    cfg = tmp_path / "config.toml"
    cfg.write_text("\n".join(f"[{s}]" for s in ("audio", "languages", "speech", "translation", "llm"))
                   + f'\n[paths]\nrecords_dir = "{tmp_path / "records"}"\n')
    monkeypatch.setenv("OMNI_CONFIG", str(cfg))
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    line = [l for l in out.splitlines() if l.startswith("2026-01-01_0000")][0]
    assert line.split()[1:3] == ["yes", "yes"]  # record, transcribe
    assert "-" in line.split()[3:]


def test_doctor_exit_code_zero():
    env = dict(os.environ, OMNI_ROOT=str(ROOT))
    proc = subprocess.run([sys.executable, "-m", "omni_recorder", "doctor"],
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[-1].endswith(" 0 FAIL")


def test_app_forces_offline_hub():
    proc = subprocess.run([sys.executable, "-c", "import omni_recorder, os; print(os.environ['HF_HUB_OFFLINE'])"],
                          capture_output=True, text=True, env={k: v for k, v in os.environ.items() if k != "HF_HUB_OFFLINE"})
    assert proc.stdout.strip() == "1"
