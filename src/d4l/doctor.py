"""`d4l doctor` — check the machine can actually run this."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import game, runtime
from .config import Config

OK, BAD, MEH = "\033[32m✓\033[0m", "\033[31m✗\033[0m", "\033[33m•\033[0m"


def _vulkan() -> tuple[bool, str]:
    exe = shutil.which("vulkaninfo")
    if not exe:
        return False, "vulkaninfo not found (install vulkan-tools to verify)"
    try:
        out = subprocess.run([exe, "--summary"], capture_output=True, text=True,
                             timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"vulkaninfo failed: {exc}"
    if out.returncode != 0:
        return False, "vulkaninfo returned an error — check your GPU drivers"
    devices = [ln.strip() for ln in out.stdout.splitlines()
               if "deviceName" in ln]
    return True, (devices[0] if devices else "Vulkan OK")


def _free_gib(path: Path) -> float:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free / 1024**3


def run(cfg: Config) -> int:
    problems = 0

    def line(good, label, detail=""):
        nonlocal problems
        mark = OK if good else BAD
        if good is None:
            mark = MEH
        elif not good:
            problems += 1
        print(f" {mark} {label}" + (f" — {detail}" if detail else ""))

    print("\nd4l doctor\n")

    umu = shutil.which("umu-run")
    line(bool(umu), "umu-launcher", umu or "missing: sudo pacman -S umu-launcher")

    ok, detail = _vulkan()
    line(ok, "Vulkan", detail)

    gpu = "NVIDIA" if runtime.is_nvidia() else (
        "AMD" if runtime.has_gpu("amdgpu") else (
            "Intel" if runtime.has_gpu("i915") or runtime.has_gpu("xe") else "unknown"))
    line(gpu != "unknown", "GPU driver", gpu)

    free = _free_gib(cfg.game_dir)
    # Diablo IV is roughly 90 GB installed, plus room for patches.
    line(free > 100, "Disk space", f"{free:.0f} GiB free at {cfg.game_dir}")

    line(None if not cfg.prefix.is_dir() else True, "Wine prefix",
         str(cfg.prefix) if cfg.prefix.is_dir() else "not created yet (run: d4l setup)")

    st = game.status(cfg)
    line(None if not st["battlenet_installed"] else True, "Battle.net",
         "installed" if st["battlenet_installed"] else "not installed (run: d4l setup)")
    line(None if not st["game_installed"] else True, "Diablo IV",
         st["game_path"] or "not installed (run: d4l install-game)")

    if os.environ.get("XDG_SESSION_TYPE"):
        print(f"\n   session: {os.environ['XDG_SESSION_TYPE']}   proton: {cfg['proton']}")

    print()
    if problems:
        print(f"{problems} problem(s) found.\n")
    return 1 if problems else 0
