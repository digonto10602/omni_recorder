"""STUB owned by speech-engineer (stage 3). Do not implement logic here in stage 1."""
from __future__ import annotations

from pathlib import Path

from .config import Config


def transcribe_call(cfg: Config, call_path: Path) -> Path:
    """Write transcript.json / transcript.md (segments: start, end, speaker, lang, text).
    Language detected per chunk, restricted to cfg languages.allowed. Frees GPU memory on return.
    Returns the transcript.json path."""
    raise NotImplementedError("stage 3 (speech-engineer)")


def translate_call(cfg: Config, call_path: Path) -> Path:
    """Write transcript_en.json / transcript_en.md from transcript.json. Returns transcript_en.json path."""
    raise NotImplementedError("stage 3 (speech-engineer)")
