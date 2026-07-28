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

    if procs.is_running_anywhere(procs.GAME):
        log.info("Diablo IV is already running.")
        return 0

    battlenet.tune_config(cfg)

    if not battlenet.start_client(cfg, verbose=verbose):
        return 1

    if not battlenet.launch_game(cfg, verbose=verbose):
        return 1

    if not wait:
        return 0

    log.info("Playing. Ctrl-C here is safe — it won't stop the game.")
    # Watch the game with whichever scope actually sees it (see launch_game).
    scope = cfg.prefix if procs.is_running(procs.GAME, cfg.prefix) else None
    try:
        procs.wait_while(procs.GAME, prefix=scope)
    except KeyboardInterrupt:
        log.warn("Interrupted — leaving the game running.")
        return 0

    log.info("Diablo IV exited.")
    if cfg["close_battlenet_after_exit"]:
        killed = procs.terminate(prefix=cfg.prefix)
        if killed:
            log.info("Closed Battle.net.")
    elif procs.is_running_anywhere(procs.BNET):
        log.info("Battle.net is still open — close it yourself, or `d4l stop`.")
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
        # Tolerant on purpose — see procs.is_running_anywhere. The GUI drives
        # its Play button off this, and showing "Play" while the game is up
        # invites relaunching over a running game.
        "battlenet_running": procs.is_running_anywhere(procs.BNET),
        "game_running": procs.is_running_anywhere(procs.GAME),
    }


def _which_umu():
    try:
        return runtime.umu_run()
    except runtime.RuntimeError_:
        return None
