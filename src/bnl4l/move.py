"""Relocating an existing install to another disk.

Deliberately conservative: the source is never deleted automatically. A
failed 90 GB move that also removed the original would mean a full
re-download and a fresh login, so the old directory is left in place and
the user removes it once the new location is proven to work.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from . import log, procs
from .config import Config
from .runtime import RuntimeError_


def dir_size(path: Path) -> int:
    """Bytes used under `path`. Does not follow symlinks — the prefix
    contains a self-referential `pfx -> .` that would otherwise recurse."""
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda _e: None):
        for name in files:
            full = os.path.join(root, name)
            try:
                if not os.path.islink(full):
                    total += os.lstat(full).st_size
            except OSError:
                pass
    return total


def human(size: float) -> str:
    for unit in ("B", "KiB", "MiB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"


def _existing_ancestor(path: Path) -> Path:
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def _same_filesystem(a: Path, b: Path) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(_existing_ancestor(b)).st_dev
    except OSError:
        return False


_PERCENT = re.compile(r"(\d{1,3})%")


def _copy(src: Path, dest: Path, progress=None) -> None:
    """Copy the tree, preserving symlinks, hardlinks and attributes.

    `progress` is called with a 0.0–1.0 fraction. When it is None, rsync's
    own output is left going to the terminal, which is what the CLI wants;
    supplying a callback captures that output and parses it instead.
    """
    dest.mkdir(parents=True, exist_ok=True)
    rsync = shutil.which("rsync")
    if rsync:
        # -a keeps symlinks as symlinks, so `pfx -> .` is copied rather than
        # followed. --info=progress2 gives one overall progress line.
        cmd = [rsync, "-aHAX", "--info=progress2", f"{src}/", f"{dest}/"]
        if progress is None:
            code = subprocess.run(cmd).returncode
        else:
            code = _copy_with_progress(cmd, progress)
        if code != 0:
            raise RuntimeError_(f"rsync failed (exit {code}).")
        if progress:
            # rsync's overall percentage habitually stops a point or two
            # short; close it out so the bar reads as finished.
            progress(1.0)
        return

    log.warn("rsync not found; copying with Python (no progress shown).")
    shutil.copytree(src, dest, symlinks=True, dirs_exist_ok=True)


def _copy_with_progress(cmd, progress) -> int:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    buffer = ""
    try:
        while True:
            chunk = proc.stdout.read(128)
            if not chunk:
                break
            buffer += chunk
            # rsync redraws its progress line with \r, not \n.
            parts = re.split(r"[\r\n]", buffer)
            buffer = parts.pop()
            for line in parts:
                found = _PERCENT.search(line)
                if found:
                    progress(min(int(found.group(1)), 100) / 100)
    finally:
        proc.stdout.close()
    return proc.wait()


def relocate(cfg: Config, destination: str, progress=None) -> int:
    src = cfg.game_dir
    dest = Path(os.path.expanduser(str(destination))).absolute()
    # Don't resolve() the whole path: it may not exist yet.
    dest = Path(os.path.normpath(dest))

    if not src.is_dir():
        raise RuntimeError_(f"Nothing to move — {src} does not exist.")
    if dest == src:
        raise RuntimeError_("Destination is the current location.")
    if str(dest).startswith(str(src) + os.sep):
        raise RuntimeError_("Destination is inside the current location.")

    for name in (procs.GAME, procs.BNET):
        # Tolerant: if something of this name is alive at all, refuse.
        # Moving 90 GB out from under a running game is unrecoverable.
        if procs.is_running_anywhere(name):
            raise RuntimeError_(
                "Diablo IV or Battle.net is still running. Close it first:\n"
                "  bnl stop --all"
            )

    if dest.exists() and any(dest.iterdir()):
        raise RuntimeError_(
            f"{dest} already exists and is not empty. Move it aside or pick "
            "another path — refusing to write into it."
        )

    size = dir_size(src)
    log.info(f"Moving {human(size)} from {src} to {dest}")

    same_fs = _same_filesystem(src, dest)
    if not same_fs:
        free = shutil.disk_usage(_existing_ancestor(dest)).free
        if free < size * 1.02:
            raise RuntimeError_(
                f"Not enough room: {human(size)} needed, "
                f"{human(free)} free at {dest}."
            )

    previous = cfg["game_dir"]

    if same_fs:
        # Same filesystem: a rename is instant and atomic, and needs no
        # extra space. Nothing is left behind to clean up.
        log.info("Same filesystem — renaming (instant).")
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.rename(src, dest)
        if progress:
            progress(1.0)
    else:
        log.info("Copying… (the game itself is most of this)")
        _copy(src, dest, progress=progress)

    cfg["game_dir"] = str(dest)
    cfg.save()

    # Prove the new location actually works before telling anyone it worked.
    if not cfg.bnet_exe.exists():
        cfg["game_dir"] = previous
        cfg.save()
        raise RuntimeError_(
            f"Battle.net was not found under {dest} after the move; the "
            "setting has been put back. The original is untouched."
        )
    if not cfg.find_game_exe():
        log.warn("Battle.net moved, but Diablo IV was not found at the new "
                 "location. Launching still works — Battle.net knows where "
                 "its game is — but check the path.")

    log.info(f"Done. Game directory is now {dest}")

    if same_fs:
        log.info("Nothing left at the old path.")
    else:
        print()
        log.info("The original is still on disk. Once `bnl play` works from")
        log.info("the new location, reclaim the space with:")
        log.info(f"  rm -rf '{src}'")
    return 0
