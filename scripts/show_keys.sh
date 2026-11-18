#!/usr/bin/env bash
# Show the omni-rec cheat sheet and wait for a key press. Used by the desktop shortcut
# (Ctrl+Shift+Alt+H) but fine to run by hand. Changes nothing.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "$SCRIPT_DIR/env.sh"
omni-rec keys
echo
printf 'Press any key to close (q / Esc / Enter all work)... '
IFS= read -rsn1 _ </dev/tty 2>/dev/null || sleep 30
echo
