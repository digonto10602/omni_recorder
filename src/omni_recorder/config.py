"""Load config.toml (standard-library tomllib) and resolve paths against the project root."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def project_root() -> Path:
    """Project root: $OMNI_ROOT if set, else two levels above src/omni_recorder."""
    env = os.environ.get("OMNI_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[2]


@dataclass
class Config:
    root: Path
    data: dict[str, Any] = field(default_factory=dict)
    source: Path | None = None

    def section(self, name: str) -> dict[str, Any]:
        value = self.data.get(name, {})
        return value if isinstance(value, dict) else {}

    def get(self, section: str, key: str, default: Any = None) -> Any:
        return self.section(section).get(key, default)

    def resolve(self, p: str | os.PathLike[str]) -> Path:
        """Relative paths are relative to the project root; absolute ones are kept."""
        path = Path(p).expanduser()
        return path if path.is_absolute() else (self.root / path)

    @property
    def records_dir(self) -> Path:
        return self.resolve(self.get("paths", "records_dir", "records"))

    @property
    def models_dir(self) -> Path:
        return self.resolve(self.get("paths", "models_dir", "models"))

    @property
    def prompts_dir(self) -> Path:
        return self.resolve(self.get("llm", "prompts_dir", "prompts/llm"))


REQUIRED_SECTIONS = ("paths", "audio", "languages", "speech", "translation", "llm")


def load_config(path: str | os.PathLike[str] | None = None, root: Path | None = None) -> Config:
    """Load config. Order: explicit path, $OMNI_CONFIG, <root>/config.toml.

    Raises FileNotFoundError or ValueError with a readable message.
    """
    root = root or project_root()
    if path is None:
        path = os.environ.get("OMNI_CONFIG") or (root / "config.toml")
    cfg_path = Path(path)
    if not cfg_path.is_file():
        raise FileNotFoundError(f"config file not found: {cfg_path}")
    try:
        with cfg_path.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"cannot parse {cfg_path}: {exc}") from exc
    missing = [s for s in REQUIRED_SECTIONS if s not in data]
    if missing:
        raise ValueError(f"{cfg_path} is missing section(s): {', '.join(missing)}")
    return Config(root=root, data=data, source=cfg_path)
