"""Building the umu/Proton environment and running things inside the prefix."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import config as cfgmod


class RuntimeError_(RuntimeError):
    """A problem with the runtime that the user can act on."""


def umu_run() -> str:
    exe = shutil.which("umu-run")
    if not exe:
        raise RuntimeError_(
            "umu-run not found. Install it with:  sudo pacman -S umu-launcher"
        )
    return exe


def has_gpu(driver: str) -> bool:
    return Path(f"/sys/module/{driver}").exists()


def is_nvidia() -> bool:
    return Path("/proc/driver/nvidia/version").exists() or has_gpu("nvidia")


def build_env(cfg: cfgmod.Config, verbose: bool = False) -> dict:
    env = dict(os.environ)

    env["WINEPREFIX"] = str(cfg.prefix)
    env["GAMEID"] = cfg["gameid"]
    env["STORE"] = cfg["store"]
    env["PROTONPATH"] = cfg["proton"]
    env["PROTON_VERB"] = "waitforexitandrun"

    if cfg["skip_runtime_update"]:
        env["UMU_RUNTIME_UPDATE"] = "0"
    if verbose:
        env["UMU_LOG"] = "1"

    # Persist the shader cache across launches so the first minutes of play
    # aren't a stutter-fest every single time.
    cache = cfg.game_dir / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    env["DXVK_STATE_CACHE_PATH"] = str(cache)
    env["VKD3D_SHADER_CACHE_PATH"] = str(cache)

    if is_nvidia():
        env["__GL_SHADER_DISK_CACHE"] = "1"
        env["__GL_SHADER_DISK_CACHE_SKIP_CLEANUP"] = "1"
        if cfg["nvidia_dlss"]:
            # DLSS needs NVAPI exposed to the game plus Proton's NGX updater.
            env["PROTON_ENABLE_NVAPI"] = "1"
            env["PROTON_ENABLE_NGX_UPDATER"] = "1"

    if cfg["raytracing"]:
        env["VKD3D_CONFIG"] = "dxr11"

    # User overrides win over everything we inferred.
    for key, value in (cfg["env"] or {}).items():
        env[str(key)] = str(value)

    return env


def wrappers(cfg: cfgmod.Config) -> list[str]:
    """Optional command prefixes (gamemode, mangohud)."""
    cmd: list[str] = []
    if cfg["gamemode"]:
        if shutil.which("gamemoderun"):
            cmd.append("gamemoderun")
        else:
            print("d4l: gamemode enabled but gamemoderun not found; skipping",
                  file=sys.stderr)
    if cfg["mangohud"]:
        if shutil.which("mangohud"):
            cmd.append("mangohud")
        else:
            print("d4l: mangohud enabled but not found; skipping", file=sys.stderr)
    return cmd


def run(cfg: cfgmod.Config, exe, args=(), *, wrap=False, verbose=False,
        detach=False, log=None, verb=None):
    """Run a Windows executable inside the prefix via umu.

    detach=True returns immediately with the Popen handle; otherwise the call
    blocks until the process exits and returns its CompletedProcess.

    `verb` overrides PROTON_VERB. The default, "waitforexitandrun", means what
    it says: Proton waits for the prefix's existing processes to finish before
    starting anything. That is right for launching into a quiet prefix and
    quite wrong for talking to a program already running in it — use "run" for
    that, or the command sits queued until the user closes everything.
    """
    cmd = (wrappers(cfg) if wrap else []) + [umu_run(), str(exe), *map(str, args)]
    env = build_env(cfg, verbose=verbose)
    if verb:
        env["PROTON_VERB"] = verb

    cfg.game_dir.mkdir(parents=True, exist_ok=True)

    if detach:
        out = open(log, "ab") if log else subprocess.DEVNULL
        return subprocess.Popen(
            cmd, env=env, stdout=out, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    return subprocess.run(cmd, env=env, check=False)
