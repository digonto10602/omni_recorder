"""`omni-rec manual` and `omni-rec keys`: both work, and the cheat sheet cannot fall behind the CLI."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from omni_recorder.cli import build_parser, main
from omni_recorder.manual import cheatsheet_text, manual_path

ROOT = Path(__file__).resolve().parents[1]


def _subcommands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)  # includes aliases
    raise AssertionError("no subcommands registered")


def _isolated(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text("\n".join(f"[{s}]" for s in ("audio", "languages", "speech", "translation", "llm"))
                   + f'\n[paths]\nrecords_dir = "{tmp_path / "records"}"\nruntime_dir = "{tmp_path / "rt"}"\n')
    monkeypatch.setenv("OMNI_CONFIG", str(cfg))


def test_keys_exits_zero_and_shows_status(tmp_path, monkeypatch, capsys):
    _isolated(tmp_path, monkeypatch)
    assert main(["keys"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Status: not recording")
    assert "cheat sheet" in out


def test_cheatsheet_alias_same_output(tmp_path, monkeypatch, capsys):
    _isolated(tmp_path, monkeypatch)
    main(["keys"])
    a = capsys.readouterr().out
    assert main(["cheatsheet"]) == 0
    assert capsys.readouterr().out == a


def test_manual_exits_zero_plain_when_not_a_terminal(capsys):
    assert main(["manual"]) == 0   # pytest captures stdout, so it is not a terminal: no pager
    out = capsys.readouterr().out
    assert out.startswith("# omni-rec user manual")


def test_manual_via_pipe_subprocess():
    proc = subprocess.run([sys.executable, "-m", "omni_recorder", "manual"], capture_output=True, text=True,
                          env=dict(os.environ, OMNI_ROOT=str(ROOT)))
    assert proc.returncode == 0 and "user manual" in proc.stdout.splitlines()[0]


def test_cheatsheet_mentions_every_subcommand_and_option():
    """Add a command or option to argparse without a cheat-sheet line and this fails."""
    text = cheatsheet_text()
    subs = _subcommands(build_parser())
    assert {"start", "stop", "status", "list", "process", "doctor", "watch", "manual", "keys", "cheatsheet"} <= set(subs)
    for name, sp in subs.items():
        assert name in text, f"cheat sheet does not mention subcommand {name!r}"
        for act in sp._actions:
            for opt in act.option_strings:
                if opt not in ("-h", "--help"):
                    assert opt in text, f"cheat sheet does not mention {name} {opt}"
    for top in build_parser()._actions:
        for opt in top.option_strings:
            assert opt in text, f"cheat sheet does not mention {opt}"


def test_manual_embeds_the_cheatsheet_verbatim_and_names_every_subcommand():
    manual = manual_path().read_text(encoding="utf-8")
    assert cheatsheet_text().strip() in manual, "docs/MANUAL.md section 4 differs from docs/CHEATSHEET.md"
    for name in _subcommands(build_parser()):
        assert f"omni-rec {name}" in manual, f"manual has no section for {name!r}"
    assert "Ctrl+Shift+Alt+H" in manual


def test_show_keys_script_is_executable_and_uses_env():
    p = ROOT / "scripts" / "show_keys.sh"
    assert os.access(p, os.X_OK)
    body = p.read_text()
    assert "env.sh" in body and "omni-rec keys" in body
