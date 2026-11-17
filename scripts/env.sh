#!/usr/bin/env bash
# Source this file (do not execute it):  source scripts/env.sh
# Keeps every cache, download and temp file inside the project (CLAUDE.md rule 4).
# It does NOT set HF_HUB_OFFLINE: setup needs downloads. The app sets it itself.

_omni_src="${BASH_SOURCE[0]:-$0}"
OMNI_ROOT="$(cd "$(dirname "$_omni_src")/.." && pwd)"
unset _omni_src
export OMNI_ROOT

export HF_HOME="$OMNI_ROOT/models/hf"
export XDG_CACHE_HOME="$OMNI_ROOT/.cache"
export PIP_CACHE_DIR="$OMNI_ROOT/.cache/pip"
export TMPDIR="$OMNI_ROOT/.tmp"
export UV_CACHE_DIR="$OMNI_ROOT/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$OMNI_ROOT/.cache/uv-python"

mkdir -p "$HF_HOME" "$XDG_CACHE_HOME" "$PIP_CACHE_DIR" "$TMPDIR" \
         "$UV_CACHE_DIR" "$UV_PYTHON_INSTALL_DIR"

case ":$PATH:" in
  *":$OMNI_ROOT/.venv/bin:"*) ;;
  *) export PATH="$OMNI_ROOT/.venv/bin:$PATH" ;;
esac
