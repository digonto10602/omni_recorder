"""STUB owned by script-writer (stages 4 and 5). Do not implement logic here in stage 1."""
from __future__ import annotations

from pathlib import Path

from .config import Config


def make_notes(cfg: Config, call_path: Path) -> Path:
    """Write notes.md using prompts/llm/01_notes.md. Returns the notes.md path."""
    raise NotImplementedError("stage 4 (script-writer)")


def make_highlights(cfg: Config, call_path: Path) -> Path:
    """Write highlights.json and cut clips/NN_slug.flac + .md. Returns the highlights.json path."""
    raise NotImplementedError("stage 4 (script-writer)")


def make_video_brief(cfg: Config, call_path: Path) -> Path:
    """Write video_brief.json / video_brief.md per prompts/llm/03_video_brief.md. Returns video_brief.json path."""
    raise NotImplementedError("stage 5 (script-writer)")
