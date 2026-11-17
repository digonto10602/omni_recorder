# System packages installed for omni_recorder

Log format (CLAUDE.md section 1, rule 3): date, package, version, source (official or AUR), which agent, why.

| date | package | version | official/AUR | agent | why |
|---|---|---|---|---|---|
| 2026-11-17 | cmake | 4.4.4-1 | official | coordinator (via pkexec) | build llama.cpp (local LLM runner) in stage 4 |
| 2026-11-17 | cppdap | 1.58.0-3 | official | coordinator (via pkexec) | dependency of cmake, pulled in automatically |
| 2026-11-17 | jsoncpp | 1.9.8-1 | official | coordinator (via pkexec) | dependency of cmake, pulled in automatically |
| 2026-11-17 | rhash | 1.4.6-1 | official | coordinator (via pkexec) | dependency of cmake, pulled in automatically |

Stage 0 (2026-11-17): no install was possible. `sudo -n true` returned "sudo: a password is required", so the two missing packages (`python-pip`, `cmake`) are listed in `reports/NEEDS_USER.md` for the user to install.

`python-pip` was not installed: optional, the project venv has its own pip (smallest-thing rule).
