# Stage 0 machine audit

- Date: 2026-11-17
- Git commit: not applicable (no git repository in this folder yet; Stage 1 creates it)
- Prompt in force: Stage 0 audit task from the coordinator, based on CLAUDE.md section 4 (stage 0 row) and section 1
- Related reports: `reports/INSTALLED.md`, `reports/NEEDS_USER.md`
- Environment file: `scripts/env.sh` does not exist yet (Stage 1), so no commands were run with it

Terms used below: **VRAM** is the memory on the graphics card. **PipeWire** is the Linux sound server. **WirePlumber** is the program that manages PipeWire's routing rules. **FLAC** is a lossless audio file format. **venv** is a self-contained Python environment. **CUDA** is NVIDIA's GPU programming platform. **nvcc** is its compiler. **ensurepip** is a Python module that installs pip inside a venv.

## System

| item | value | command |
|---|---|---|
| Kernel | `Linux omnicommander 7.2.15-1-omarchy`, built 2026-11-02 | `uname -a` |
| Distro | Omarchy 4.5.0 (Arch Linux based, `ID_LIKE=arch`) | `cat /etc/os-release` |
| Hostname | `omnicommander` | `hostname` |
| Window manager | Hyprland 0.56.2 (commit efb50993) | `hyprctl version` |
| CPU | Intel Core i7-12700KF, 12 cores, 20 threads | `lscpu` |
| RAM | 31 GiB total, 13 GiB used, 17 GiB available | `free -h` |
| Swap | 62 GiB total, 2.0 GiB used | `free -h` |
| Free disk (where `~/omni_recorder` lives) | 1.2 TB free of 1.9 TB (`/dev/mapper/root`, 39% used) | `df -h /home/digimonk/omni_recorder` |

## GPU

| item | value | command |
|---|---|---|
| Card | NVIDIA GeForce RTX 3070 (PCI 01:00.0, GA104) | `nvidia-smi --query-gpu=name,...` |
| Driver | 615.78.08 | same |
| CUDA runtime version reported by the driver | 13.4 (driver-side "UMD" version) | `nvidia-smi` header |
| Total VRAM | 8192 MiB (8 GiB) | `nvidia-smi --query-gpu=memory.total` |
| Free VRAM at audit time | 6165 MiB (about 6.0 GiB), at 14:29 local time | `nvidia-smi --query-gpu=memory.free` |
| Other GPU users at audit time | Chrome GPU process 306 MiB, VS Code 42 MiB, Nautilus 34 MiB (about 0.4 GiB together) | `nvidia-smi --query-compute-apps` |
| GPU load at audit time | 8 % utilisation, 44 W, 46 °C | `nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,power.draw` |
| Vulkan | `vulkaninfo` not installed; not needed for the NVIDIA path | `command -v vulkaninfo` |
| AMD ROCm | no AMD card; `rocminfo` not present | `command -v rocminfo` |
| Intel GPU | none (the CPU has integrated graphics, not used for this work) | `lspci` |
| `nvcc` (CUDA compiler) | **missing**. Recorded only, not installed (see `reports/NEEDS_USER.md`) | `nvcc --version` |

## Audio

| item | value | command |
|---|---|---|
| PipeWire | 1.6.9 (libpipewire 1.6.9) | `pipewire --version` |
| WirePlumber | 0.5.18 (libwireplumber 0.5.18) | `wireplumber --version` |
| pw-record | present, `/usr/bin/pw-record`, libpipewire 1.6.9 | `pw-record --version` |
| pw-dump | present, `/usr/bin/pw-dump` | `command -v pw-dump` |
| pw-link | present, `/usr/bin/pw-link` | `command -v pw-link` |
| pw-cli | present, `/usr/bin/pw-cli` | `command -v pw-cli` |
| pactl | present, `/usr/bin/pactl`; server "PulseAudio (on PipeWire 1.6.9)", server version 15.0.0 | `pactl info` |
| wpctl | present, `/usr/bin/wpctl` | `command -v wpctl` |
| Default sink (output) | `alsa_output.pci-0000_00_1f.3.analog-stereo` ("Built-in Audio Analog Stereo") | `pactl info` |
| Default source (microphone) | `alsa_input.usb-BLUE_MICROPHONE_Blue_Snowball_<usb-serial-redacted>-00.analog-stereo` ("Blue Snowball") | `pactl info` |
| Default sample format | float32 little-endian, 2 channels, 48000 Hz | `pactl info` |
| Other sources | Brio 101 Mono (webcam microphone), Built-in Audio Analog Stereo | `wpctl status` |
| Other sinks | HDMI output to a DELL UZ2715H monitor (GA104 HDMI 2) | `wpctl status` |
| Chrome audio streams | Two active Chromium output streams (`output_FL`, `output_FR`) linked to ALC897 Analog playback. A "Google Chrome input" client exists (pid 7044). Chromium 155 is also running. | `wpctl status`, `pw-dump` not run in full |
| Other audio clients | Superwhisper (pid 1926), Steam, quickshell, xdg-desktop-portal-hyprland | `wpctl status` |

Note: the `wpctl status` output lists the Brio 101 webcam as an audio and video device. Its microphone is another possible source for the mic track, but the Blue Snowball is the default.

## Tools

| tool | status | version | command |
|---|---|---|---|
| ffmpeg | present, `/usr/bin/ffmpeg` | n9.0.2 (Arch package 2:9.0.2-2) | `ffmpeg -version` |
| FLAC encoder in ffmpeg | available (`A....D flac`, FLAC, Free Lossless Audio Codec) | - | `ffmpeg -encoders \| grep flac` |
| ffprobe | present, `/usr/bin/ffprobe` | same build as ffmpeg | `command -v ffprobe` |
| sox | **missing** (optional, not installed) | - | `command -v sox` |
| git | present, `/usr/bin/git` | 2.56.0 | `git --version` |
| gh | present, via mise (`~/.local/share/mise/installs/gh/...`), not from pacman | 2.103.3 (2026-10-26) | `gh --version` |
| python3 | present, `/usr/bin/python3` | 3.14.8 (Arch package 3.14.8-1) | `python3 --version` |
| pip (system) | **missing**. `python3 -m pip` says "No module named pip"; `python-pip` package not installed | - | `python3 -m pip --version` |
| venv and ensurepip modules | importable (`import venv, ensurepip` succeeds). The actual venv creation test was **denied** by the permission system and not run | - | `python3 -c 'import ensurepip, venv'` |
| uv | present, via mise | 0.13.7 | `uv --version` |
| cmake | **missing** (not installed) | - | `cmake --version` |
| gcc / g++ | present, `/usr/bin/gcc`, `/usr/bin/g++` | gcc 16.2.1 | `gcc --version` |
| make | present, `/usr/bin/make` | GNU Make 4.4.1 | `make --version` |
| pkg-config | present, `/usr/bin/pkg-config` | 3.0.10 (pkgconf) | `pkg-config --version` |
| base-devel | installed | 1-2 | `pacman -Q base-devel` |
| jq | present, `/usr/bin/jq` | 1.8.2 | `jq --version` |
| curl | present, `/usr/bin/curl` | 8.23.0 | `curl --version` |
| yay (AUR helper) | present, `/usr/bin/yay` | v13.0.1 | `yay --version` |
| graphify | present, `/home/digimonk/.local/bin/graphify` (`graphify --help` prints its usage) | version not printed by the tool | `command -v graphify` |
| Chrome (browser) | `google-chrome-stable`, `/usr/bin/google-chrome-stable` (the Chrome command name) | Google Chrome 157.0.8103.50 | `google-chrome-stable --version` |
| Chromium (second browser) | `chromium`, `/usr/bin/chromium` | Chromium 155.0.8059.84 (Arch Linux) | `chromium --version` |
| `google-chrome` / `chromium-browser` | not present (not needed; the Chrome command is `google-chrome-stable`) | - | `command -v` |

## GitHub

| item | value | command |
|---|---|---|
| `gh auth status` | Logged in to github.com as `digonto10602` (keyring storage). Scopes: gist, read:org, repo, workflow. Protocol: https. | `gh auth status` (exit 0) |
| `gh api user --jq .login` | `digonto10602` | `gh api user --jq .login` (exit 0) |
| Note | CLAUDE.md section 8 says the account is tied to the user's e-mail address. The e-mail address is not recorded here. The login name is a required fact for Stage 1b and is not secret. The login matches the account in the project rules. | - |

## Python

| item | value | command |
|---|---|---|
| System Python | 3.14.8 at `/usr/bin/python3` | `python3 --version` |
| `ensurepip` and `venv` modules | import successfully | `python3 -c 'import ensurepip, venv'` |
| venv creation in `~/omni_recorder/.tmp` | **not tested**. The shell command was denied by the permission system. Not retried. | - |
| Package manager | `uv` 0.13.7 available. Project packages go in `~/omni_recorder/.venv` (CLAUDE.md rule 4). | `uv --version` |

## Missing / installed

| item | result |
|---|---|
| Packages installed by this audit | **None.** `sudo -n true` returned "sudo: a password is required" (exit 1), so no `sudo pacman` command was possible. |
| Packages missing and needed by the project | `cmake` (needed later for llama.cpp, not Stage 0), `python-pip` (optional, the venv has its own pip) |
| Command for the user | `sudo pacman -S --needed cmake python-pip` (see `reports/NEEDS_USER.md`) |
| Packages recorded as missing but not needed now | `sox` (optional), `nvcc` / CUDA toolkit (decide when building llama.cpp), `vulkaninfo` (not needed for NVIDIA) |
| Already present, no install needed | `pipewire`, `wireplumber`, `libpulse` (`pactl`), `ffmpeg`, `git`, `github-cli` (through mise), `python`, `jq`, `base-devel`, `pkgconf`, `gcc`, `make`, `curl`, `yay` |
| Installed on this system (project log) | Nothing installed yet. See `reports/INSTALLED.md`. |

## Notes for later stages

1. **VRAM budget.** The RTX 3070 has 8192 MiB (8 GiB) of VRAM. About 6165 MiB (about 6.0 GiB) was free at audit time, while Chrome, VS Code and Nautilus used about 0.4 GiB. The project should plan for about 5.5 GiB of usable VRAM, and the audit does not measure the speech or language models. Estimated sizes (not measured here): Whisper large-v3 in half precision (fp16) needs roughly 3 GB; Whisper medium needs roughly 1.5 GB. The language model must share the same card, and the rule "one model loaded at a time" (CLAUDE.md section 2) is required on this card. These numbers are planning estimates; Stage 3 and 4 must measure them.
2. **Chrome command.** Use `google-chrome-stable` (version 157.0.8103.50). Chromium 155 is also installed and is running with its own audio streams, so the recorder must target the stream whose application name is "Google Chrome" (its PipeWire client is "Google Chrome input", pid 7044). Stage 2 should confirm which streams carry Messenger calls.
3. **CUDA compiler.** `nvcc` is missing. The driver (615.78.08) is installed, so GPU inference through prebuilt tools is possible without it. Building llama.cpp with CUDA would need the CUDA toolkit. Decide in the LLM stage (Stage 4 or 5).
4. **Python.** Python 3.14.8 is the system version. Check that the chosen speech and LLM packages support it; if not, `uv` can install another Python inside the project venv without touching the system.
5. **Audio default.** The default microphone is the Blue Snowball USB microphone. The default sink is the built-in analog output. Stage 2 must record the Chrome stream directly, not the default monitor, when possible (CLAUDE.md section 2).
6. **Venv test still open.** The `venv` creation test in `~/omni_recorder/.tmp` was denied. Run it when permission is available or at the start of Stage 1.
7. **Superwhisper.** It is running as an audio client (pid 1926). It may hold the microphone; check this during Stage 2 so the recorder does not compete with it.
