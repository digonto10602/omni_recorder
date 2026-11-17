# Needs user action

## 1. Install missing system packages (Stage 0, 2026-11-17) — RESOLVED: cmake installed via pkexec on 2026-11-17 (user approved pkexec); python-pip skipped as optional

**Why it is needed:** the runner agent cannot install packages because `sudo` asks for a password, and the agent must not work around that (CLAUDE.md section 1, rule 3). `sudo -n true` returned `sudo: a password is required` (exit code 1).

**Missing packages found by the audit** (checked with `pacman -Q`):

| package | status | needed for |
|---|---|---|
| `cmake` | not installed | Building llama.cpp (the local language model runner), expected in a later stage. Not needed for Stage 0 itself. |
| `python-pip` | not installed | Optional. Python's package installer as a system tool. The project venv (`.venv`) can use its own pip through `ensurepip`, which is present. Install only if you want a system-wide `pip`. |

**Command for you to run** (installs only these two packages, no upgrade):

```
sudo pacman -S --needed cmake python-pip
```

Do not run `pacman -Syu`. The audit did not test whether pacman would demand a full upgrade, because sudo was not available.

**Not missing:** `github-cli` (`gh`) is not installed through pacman, but `gh` 2.103.3 is present through mise, so no install is needed. `ffmpeg`, `git`, `python`, `jq`, `pipewire`, `wireplumber`, `libpulse` (provides `pactl`), `base-devel` are all installed.

## 2. GitHub login

`gh auth status` shows the account `digonto10602` is logged in. No action needed.

## 3. CUDA toolkit (not needed yet)

`nvcc` is missing. The NVIDIA driver is installed (615.78.08), but the CUDA compiler (the toolkit that builds GPU code) is not. Decide later, when building llama.cpp, whether to install `cuda` through pacman. Not requested now; no action needed yet.

## 4. Python venv test not completed — handled in Stage 1 (builder creates .venv)

The audit tried to test `python3 -m venv` inside `~/omni_recorder/.tmp`. The permission system denied that shell command, so the test did not run. The modules `ensurepip` and `venv` import correctly, which is strong evidence that venv works, but the test itself is still open. The coordinator or the user should decide whether to allow it or run it later during Stage 1 setup.
