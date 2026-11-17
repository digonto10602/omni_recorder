#!/usr/bin/env bash
# Privacy gate (CLAUDE.md section 8). Run before every push.
# Exit 1 and list offending files if any tracked or staged file is private,
# audio, a model file, over 1 MB, or looks like a real transcript/notes file.
# Works in a repository with zero commits. Optional argument: repo directory.
set -u

REPO="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$REPO" || { echo "cannot enter $REPO" >&2; exit 2; }
git rev-parse --git-dir >/dev/null 2>&1 || { echo "not a git repository: $REPO" >&2; exit 2; }

bad=0
report() { echo "  REJECT ($1): $2"; bad=1; }

# Tracked plus staged files, unique, NUL-safe.
mapfile -d '' files < <( { git ls-files -z; git diff --cached --name-only -z; } | sort -zu )

for f in "${files[@]}"; do
  [ -n "$f" ] || continue
  lower="${f,,}"
  base="${lower##*/}"

  case "$f" in
    records/*|models/*|.venv/*|.cache/*|.tmp/*|vendor/*) report "private folder" "$f" ;;
  esac

  case "$lower" in
    *.flac|*.wav|*.mp3|*.ogg|*.opus|*.m4a|*.webm|*.mkv|*.mp4) report "audio/video extension" "$f" ;;
    *.gguf|*.bin|*.safetensors|*.pt|*.onnx) report "model file" "$f" ;;
  esac

  case "$f" in
    tests/fixtures/*) ;;
    *)
      case "$base" in
        transcript.*|transcript_en.*|notes.md|highlights.json|video_brief.*)
          report "transcript/notes-like name" "$f" ;;
      esac ;;
  esac

  # Size check: staged/working-tree file; skip if deleted.
  if [ -f "$f" ]; then
    size=$(stat -c %s -- "$f")
    if [ "$size" -gt 1048576 ]; then report "larger than 1 MB ($size bytes)" "$f"; fi
  fi
done

email="$(git config --local user.email 2>/dev/null || true)"
if [ -z "$email" ]; then
  echo "  REJECT (git identity): git config --local user.email is not set"
  bad=1
fi

if [ "$bad" -ne 0 ]; then
  echo "prepush_check: FAILED" >&2
  exit 1
fi
echo "prepush_check: OK (${#files[@]} files checked)"
exit 0
