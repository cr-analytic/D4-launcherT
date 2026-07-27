"""The one-click play flow."""

from __future__ import annotations

from . import battlenet, log, procs, runtime
from .config import Config


def play(cfg: Config, verbose: bool = False, wait: bool = True) -> int:
    """Start Battle.net if needed, launch Diablo IV, tidy up afterwards.

    This is the whole point of the tool: from the user's side it is one
    click, and Battle.net is an implementation detail they never touch after
    the first login.
    """
    if not cfg.bnet_exe.exists():
        log.error("Battle.net isn't installed yet. Run `d4l setup` first.")
        return 1

    if procs.is_running(procs.GAME, cfg.prefix):
        log.info("Diablo IV is already running.")
        return 0

    battlenet.tune_config(cfg)

    if not battlenet.start_client(cfg, verbose=verbose):
        return 1

    if not battlenet.launch_game(cfg, verbose=verbose):
        return 1

    if not wait:
        return 0

    log.info("Playing. This window can stay open; it cleans up on exit.")
    try:
        procs.wait_while(procs.GAME, prefix=cfg.prefix)
    except KeyboardInterrupt:
        log.warn("Interrupted — leaving the game running.")
        return 0

    log.info("Diablo IV exited.")
    if cfg["close_battlenet_after_exit"]:
        killed = procs.terminate(prefix=cfg.prefix)
        if killed:
            log.info("Closed Battle.net.")
    return 0


def status(cfg: Config) -> dict:
    """A snapshot of what is installed and running, for the CLI and the GUI."""
    exe = cfg.find_game_exe()
    return {
        "umu": _which_umu(),
        "prefix": cfg.prefix.is_dir(),
        "battlenet_installed": cfg.bnet_exe.exists(),
        "game_installed": exe is not None,
        "game_path": str(exe) if exe else None,
        "battlenet_running": procs.is_running(procs.BNET, cfg.prefix),
        "game_running": procs.is_running(procs.GAME, cfg.prefix),
    }


def _which_umu():
    try:
        return runtime.umu_run()
    except runtime.RuntimeError_:
        return None
