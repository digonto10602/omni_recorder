"""STUB owned by audio-engineer (stage 2). Do not implement logic here in stage 1."""
from __future__ import annotations

from pathlib import Path

from .config import Config


def start_recording(cfg: Config) -> str:
    """Begin recording me.flac / them.flac / mix.flac / meta.json. Returns the call_id.
    Must register runtime-only PipeWire objects so cleanup_leftovers() can remove them."""
    raise NotImplementedError("stage 2 (audio-engineer)")


def stop_recording(cfg: Config) -> Path:
    """Stop the running recording, finalize files, remove runtime objects. Returns the call folder."""
    raise NotImplementedError("stage 2 (audio-engineer)")


def recording_status(cfg: Config) -> str | None:
    """Return the call_id of a running recording, or None."""
    raise NotImplementedError("stage 2 (audio-engineer)")
