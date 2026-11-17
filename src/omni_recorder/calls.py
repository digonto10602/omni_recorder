"""Which pipeline steps are done for a call folder (judged by output files present)."""
from __future__ import annotations

from pathlib import Path

# step name -> files that must all exist for the step to count as done
STEP_FILES: dict[str, tuple[str, ...]] = {
    "record": ("me.flac", "them.flac", "meta.json"),
    "transcribe": ("transcript.json", "transcript.md"),
    "translate": ("transcript_en.json", "transcript_en.md"),
    "notes": ("notes.md",),
    "highlights": ("highlights.json",),
    "brief": ("video_brief.json", "video_brief.md"),
}


def steps_done(call_path: Path) -> dict[str, bool]:
    return {step: all((call_path / f).is_file() for f in files) for step, files in STEP_FILES.items()}
