import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def project_tmp() -> Path:
    """Scratch folder inside the project (.tmp), never the system /tmp."""
    base = Path(os.environ.get("TMPDIR") or ROOT / ".tmp")
    if not str(base.resolve()).startswith(str(ROOT.resolve())):
        base = ROOT / ".tmp"
    base.mkdir(parents=True, exist_ok=True)
    return base


@pytest.fixture
def tmp_repo(project_tmp, tmp_path_factory):
    """Throwaway git repo with zero commits, under the project's .tmp folder."""
    import tempfile
    d = Path(tempfile.mkdtemp(prefix="prepush_", dir=project_tmp))
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    subprocess.run(["git", "-C", str(d), "config", "--local", "user.email", "t@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(d), "config", "--local", "user.name", "t"], check=True)
    yield d
    import shutil
    shutil.rmtree(d, ignore_errors=True)
