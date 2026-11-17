"""prepush_check.sh must reject private/audio/model/big/transcript-like files. Synthetic content only."""
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prepush_check.sh"


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def run_check(repo):
    return subprocess.run(["bash", str(SCRIPT), str(repo)], capture_output=True, text=True)


def add(repo, rel, content=b"synthetic", stage=True):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    if stage:
        git(repo, "add", "-f", rel)
    return p


def test_clean_repo_passes_with_zero_commits(tmp_repo):
    add(tmp_repo, "src/a.py", b"print('hi')\n")
    add(tmp_repo, "README.md", b"# synthetic\n")
    r = run_check(tmp_repo)
    assert r.returncode == 0, r.stdout + r.stderr


def test_empty_repo_passes(tmp_repo):
    assert run_check(tmp_repo).returncode == 0


@pytest.mark.parametrize("rel", [
    "records/x.txt",                    # fake records/ file
    "fake_call.flac",                   # fake audio file
    "UPPER.WAV",                        # case-insensitive extension
    "clip.mp4",
    "models/readme.txt",
    ".venv/x.py",
    ".cache/x.txt",
    ".tmp/x.txt",
    "vendor/x.txt",
    "weights.gguf",
    "weights.safetensors",
    "m.onnx",
    "m.pt",
    "m.bin",
    "transcript.json",
    "sub/transcript_en.md",
    "notes.md",
    "highlights.json",
    "video_brief.md",
    "video_brief.json",
])
def test_rejects_bad_staged_file(tmp_repo, rel):
    add(tmp_repo, "ok.txt", b"fine")
    add(tmp_repo, rel)
    r = run_check(tmp_repo)
    assert r.returncode == 1, r.stdout + r.stderr
    assert rel in r.stdout


def test_rejects_file_over_1mb(tmp_repo):
    add(tmp_repo, "big.txt", b"x" * (2 * 1024 * 1024))
    r = run_check(tmp_repo)
    assert r.returncode == 1
    assert "big.txt" in r.stdout


def test_rejects_committed_file_too(tmp_repo):
    add(tmp_repo, "records/x.txt")
    git(tmp_repo, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q", "-m", "synthetic")
    r = run_check(tmp_repo)
    assert r.returncode == 1 and "records/x.txt" in r.stdout


def test_fixtures_folder_allows_transcript_names(tmp_repo):
    add(tmp_repo, "tests/fixtures/transcript.json", b"{}")
    add(tmp_repo, "tests/fixtures/notes.md", b"synthetic")
    r = run_check(tmp_repo)
    assert r.returncode == 0, r.stdout + r.stderr


def test_ignored_untracked_file_not_flagged(tmp_repo):
    (tmp_repo / ".gitignore").write_text("records/\n")
    git(tmp_repo, "add", ".gitignore")
    add(tmp_repo, "records/x.txt", stage=False)
    assert run_check(tmp_repo).returncode == 0


def test_requires_local_identity(tmp_repo):
    git(tmp_repo, "config", "--local", "--unset", "user.email")
    add(tmp_repo, "ok.txt")
    # a global email may exist on the machine; the check must look at --local only
    r = run_check(tmp_repo)
    assert r.returncode == 1 and "user.email" in r.stdout


def test_filenames_with_spaces(tmp_repo):
    add(tmp_repo, "my records/a b.flac")
    r = run_check(tmp_repo)
    assert r.returncode == 1 and "a b.flac" in r.stdout
