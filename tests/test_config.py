from pathlib import Path

import pytest

from omni_recorder.config import load_config, project_root


def test_project_config_loads():
    cfg = load_config()
    assert cfg.get("audio", "sample_rate") == 48000
    assert cfg.get("languages", "allowed") == ["bn", "en"]
    assert cfg.records_dir == project_root() / "records"
    assert cfg.prompts_dir == project_root() / "prompts" / "llm"


def test_relative_and_absolute_resolution(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("\n".join(f"[{s}]" for s in
                 ("paths", "audio", "languages", "speech", "translation", "llm")))
    cfg = load_config(f, root=tmp_path)
    assert cfg.resolve("records") == tmp_path / "records"
    assert cfg.resolve("/abs/x") == Path("/abs/x")


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "none.toml")


def test_missing_sections(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("[paths]\n")
    with pytest.raises(ValueError, match="missing section"):
        load_config(f, root=tmp_path)


def test_bad_toml(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("[paths\n")
    with pytest.raises(ValueError, match="cannot parse"):
        load_config(f, root=tmp_path)


def test_no_model_names_hardcoded_in_python():
    src = Path(__file__).resolve().parents[1] / "src" / "omni_recorder"
    text = "\n".join(p.read_text() for p in src.glob("*.py")).lower()
    for word in ("whisper-", "large-v3", "tugstugi", "indictrans", ".gguf"):
        assert word not in text
