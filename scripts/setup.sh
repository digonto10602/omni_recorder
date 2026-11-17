#!/usr/bin/env bash
# Create the project virtual environment and install the package.
# Idempotent. Changes nothing outside ~/omni_recorder. Downloads Python 3.12
# (into .cache/uv-python) and Python packages only. No model files.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "$SCRIPT_DIR/env.sh"
cd "$OMNI_ROOT"

command -v uv >/dev/null || { echo "uv is required (https://docs.astral.sh/uv/)" >&2; exit 1; }

if [ ! -x .venv/bin/python ]; then
  uv venv --python 3.12 .venv
else
  echo ".venv already exists, reusing it."
fi

uv pip install --python .venv/bin/python -e '.[dev]'

echo
echo "Setup done. Next:  source scripts/env.sh && omni-rec doctor"
