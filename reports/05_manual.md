# Report 05: user manual, cheat sheet and desktop shortcut

- Date: 2026-11-17
- Git commit: not committed yet (repo-keeper commits). Base: previous stage.
- Prompt in force: coordinator task "write the full user manual and add a desktop cheat-sheet shortcut"
- Related reports: `reports/04_recording.md`
- Author: builder agent

## Files

| file | change |
|---|---|
| `docs/MANUAL.md` | new: full manual (12 sections) |
| `docs/CHEATSHEET.md` | new: the single source of the cheat-sheet text |
| `src/omni_recorder/manual.py` | new: `show_manual()`, `show_keys()`, `status_line()` |
| `src/omni_recorder/cli.py` | added `manual`, `keys` (alias `cheatsheet`) |
| `scripts/show_keys.sh` | new: sources `env.sh`, runs `omni-rec keys`, waits for a key |
| `tests/test_manual.py` | new: 7 tests |
| `README.md` | shortened command section, links to `docs/MANUAL.md` |
| `~/.config/hypr/bindings.lua` | the one approved exception to CLAUDE.md rule 1 (below) |

How the texts stay consistent: `omni-rec keys` prints `docs/CHEATSHEET.md`; the manual embeds that same text
verbatim in section 4; a test fails if they differ, and another fails if any argparse subcommand or option
(including aliases) is missing from the cheat sheet or any subcommand lacks `omni-rec <name>` in the manual.

## The bindings.lua change (outside the project, approved)

- Key check: `hyprctl binds -j` at modmask 13 (Ctrl+Shift+Alt) listed only `R` (omni-reminder, two entries) and
  `TAB` (focus previous monitor). `omarchy menu keybindings --print` showed no `H` on that modifier set. So **H was free**.
- Backup made first: `/home/digimonk/.config/hypr/bindings.lua.bak.1794961128`
- Lines appended at the end of `/home/digimonk/.config/hypr/bindings.lua` (a blank line, a comment, and):

```lua
o.bind("CTRL + SHIFT + ALT + H", "omni-rec cheat sheet", "omarchy-launch-tui --app-id=TUI.float bash /home/digimonk/omni_recorder/scripts/show_keys.sh")
```

- `hyprctl reload` then `hyprctl configerrors`: empty (clean). `hyprctl binds -j` now lists key H, modmask 13, description "omni-rec cheat sheet".
- Window: I did **not** use `omarchy-launch-floating-terminal-with-presentation`. I read it: it shows the Omarchy logo first and
  a "Done!" prompt that needs a second key press after the sheet. I used `omarchy-launch-tui` (also read-only, in
  `/usr/share/omarchy/bin`) with `--app-id=TUI.float`. Omarchy's own rules (`/usr/share/omarchy/default/hypr/apps/system.lua`)
  already float and center class `TUI.float`, and tag it `terminal`, which makes it transparent (opacity 0.985 / 0.96).
  So **no window rule was added**, and the wiki page was not needed.
- To undo: delete the comment and `o.bind` line, or restore the backup, then `hyprctl reload`.
- Nothing else outside the project was touched. Ctrl+Shift+Alt+R was not changed.

## Check results

| check | command | result |
|---|---|---|
| unit tests | `source scripts/env.sh && pytest -q` | 93 passed, 7 skipped (the 7 live-audio tests), 2.7 s |
| manual | `omni-rec manual \| head -5` | prints title and intro, exit 0 |
| cheat sheet | `omni-rec keys`, `omni-rec cheatsheet` | exit 0; first line `Status: not recording` |
| privacy gate | `bash scripts/prepush_check.sh` | `prepush_check: OK (49 files checked)` |
| config errors | `hyprctl reload; hyprctl configerrors` | empty |
| popup launch | `hyprctl dispatch 'hl.dsp.exec_cmd("omarchy-launch-tui --app-id=TUI.float bash .../show_keys.sh")'`, then `hyprctl clients -j` | window class `TUI.float`, floating true, size 875x600, tags `floating-window`, `terminal`, `transparent-window`; then closed it |

Not tested: the actual key press (I cannot press keys; the bind is registered, the launch command it runs works), and the
interactive pager (`less -R`) on a real terminal (the code path is plain; only the non-terminal path is covered by tests).

## Problems and assumptions

1. `hyprctl dispatch exec ...` fails on this Hyprland version (Lua config: dispatchers are Lua expressions), so I launched with
   `hl.dsp.exec_cmd(...)`, which is what `o.bind` does internally.
2. The popup opened on workspace 21 / monitor 2 in my test (wherever the focus was at the time); a real key press opens it on the focused workspace.
3. The manual describes `process` and `watch` as "planned - stage N" using only CLAUDE.md section 2; their outputs are not invented.
   When those stages land, update `docs/CHEATSHEET.md` and the manual's section 5 (tests will force the cheat sheet to stay in step).
4. Manual statements about `meta.json` and warnings come from `finalize.py`, `audiocheck.py` and `reports/04_recording.md`; the sample
   outputs in the manual are illustrative numbers.
5. The manual suggests `wpctl set-default <id>` as one way a user can change the default microphone; the app itself never runs it.
6. graphify: no `graphify-out/graph.json` exists, so files were read directly.
7. No git commit made.

## Installed on this system

Nothing new (see `reports/INSTALLED.md` for earlier entries).
