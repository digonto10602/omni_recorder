"""omni_recorder: local call recorder and script maker. Runs fully offline."""
import os as _os

# CLAUDE.md rule 6: the app makes no network calls. This runs before any
# Hugging Face library can be imported. A setup/download step must export
# HF_HUB_OFFLINE=0 explicitly (setdefault never overrides an explicit value).
_os.environ.setdefault("HF_HUB_OFFLINE", "1")
_os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

__version__ = "0.1.0"
