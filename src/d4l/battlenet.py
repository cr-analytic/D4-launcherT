"""Installing, configuring and driving the Battle.net client."""

from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request

from . import log, procs, runtime
from .config import BNET_INSTALLER_URL, D4_PRODUCT, Config

UA = "Mozilla/5.0 (X11; Linux x86_64) d4-launcher"

# Battle.net.config's GameLaunchWindowBehavior values. Anything not listed
# here (including "") means "don't touch the user's setting".
#
# "close" is offered but not recommended: the client exits during the launch,
# so there is nothing left for a follow-up --exec to talk to, and a retry then
# starts a fresh Battle.net rather than reaching the running one.
WINDOW_BEHAVIOUR = {"keep": "0", "minimize": "1", "minimise": "1", "close": "2"}


# --------------------------------------------------------------------------
# Installation
# --------------------------------------------------------------------------

def download_installer(cfg: Config, force: bool = False) -> None:
    dest = cfg.installer
    if dest.exists() and not force:
        log.info(f"Battle.net installer already present ({dest})")
        return

    cfg.game_dir.mkdir(parents=True, exist_ok=True)
    log.info("Downloading the Battle.net installer from Blizzard…")
    tmp = dest.with_suffix(".part")
    req = urllib.request.Request(BNET_INSTALLER_URL, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as fh:
            shutil.copyfileobj(resp, fh)
    except (urllib.error.URLError, OSError) as exc:
        tmp.unlink(missing_ok=True)
        raise runtime.RuntimeError_(
            f"Could not download the Battle.net installer: {exc}\n"
            f"Download it manually from https://battle.net/download and save it as:\n"
            f"  {dest}"
        ) from exc

    # Make sure we got an actual Windows executable and not an error page.
    with open(tmp, "rb") as fh:
        if fh.read(2) != b"MZ":
            tmp.unlink(missing_ok=True)
            raise runtime.RuntimeError_(
                "The downloaded file is not a Windows executable (Blizzard may have "
                "returned an error page). Download it manually from "
                f"https://battle.net/download and save it as:\n  {dest}"
            )
    tmp.replace(dest)
    log.info(f"Installer saved to {dest}")


def install(cfg: Config, verbose: bool = False) -> None:
    """Run the Battle.net setup inside the prefix. Blocks until it finishes."""
    if cfg.bnet_exe.exists():
        log.info("Battle.net is already installed in the prefix.")
        return

    download_installer(cfg)
    log.info("Installing Battle.net (this creates the Wine prefix on first run)…")
    log.info("The Battle.net window will appear — log in and let it finish.")
    runtime.run(cfg, cfg.installer, verbose=verbose)

    if not cfg.bnet_exe.exists():
        raise runtime.RuntimeError_(
            "Battle.net setup finished but Battle.net.exe was not found at\n"
            f"  {cfg.bnet_exe}\n"
            "Re-run `d4l setup` or check the log with `d4l logs`."
        )
    log.info("Battle.net installed.")


# --------------------------------------------------------------------------
# Client configuration
# --------------------------------------------------------------------------

def tune_config(cfg: Config) -> None:
    """Best-effort tweaks to Battle.net.config to keep the client out of the way.

    Only touches documented keys, and silently does nothing if the file does
    not exist yet (it is written on the client's first run) or is unparseable.
    """
    path = cfg.bnet_config
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(data, dict):
        return

    client = data.setdefault("Client", {})
    if not isinstance(client, dict):
        return

    before = json.dumps(data, sort_keys=True)

    behaviour = WINDOW_BEHAVIOUR.get(str(cfg["battlenet_on_game_launch"]).lower())
    if behaviour is not None:
        client["GameLaunchWindowBehavior"] = behaviour
    if cfg["disable_bnet_hardware_accel"]:
        # Blizzard's own troubleshooting step; the CEF-based UI renders far
        # more reliably under Wine without it.
        client["HardwareAcceleration"] = "false"

    if json.dumps(data, sort_keys=True) == before:
        return

    try:
        tmp = path.with_suffix(".config.d4l-tmp")
        tmp.write_text(json.dumps(data, indent=4))
        tmp.replace(path)
        log.info("Tuned Battle.net client settings.")
    except OSError as exc:
        log.warn(f"Could not write Battle.net.config: {exc}")


# --------------------------------------------------------------------------
# Launching
# --------------------------------------------------------------------------

def start_client(cfg: Config, verbose: bool = False, timeout: float = 180.0) -> bool:
    """Start Battle.net if it isn't already up, and wait until it is usable.

    Returns True once the client is ready to accept --exec commands.
    """
    if procs.is_running(procs.BNET, cfg.prefix):
        log.info("Battle.net is already running.")
        return True

    if not cfg.bnet_exe.exists():
        raise runtime.RuntimeError_(
            "Battle.net is not installed yet. Run `d4l setup` first."
        )

    log.info("Starting Battle.net…")
    runtime.run(cfg, cfg.bnet_exe, detach=True, verbose=verbose,
                log=cfg.game_dir / "battlenet.log")

    if not procs.wait_for(procs.BNET, timeout=timeout, prefix=cfg.prefix):
        log.error("Battle.net did not start within "
                  f"{int(timeout)}s. See `d4l logs`.")
        return False

    # Battle.net.exe existing is not the same as the client being ready: the
    # UI is Chromium-based and only becomes interactive once its helper
    # renderer processes are up. Waiting for those is what makes the
    # subsequent `--exec launch` reliable.
    if procs.wait_for(procs.BNET_HELPER, timeout=90, prefix=cfg.prefix):
        log.info("Battle.net is up.")
    else:
        log.warn("Battle.net UI helpers not detected; continuing anyway.")
    return True


def exec_command(cfg: Config, command: str, verbose: bool = False) -> None:
    """Send a command to the running Battle.net client.

    PROTON_VERB=run is essential here. The default verb,
    "waitforexitandrun", makes Proton wait for the prefix's existing
    processes to exit before starting the executable — so the command never
    reaches the running client at all. It sits queued until the user closes
    Battle.net, and *then* runs `Battle.net.exe`, which with no client left
    to talk to simply starts a new one. That is a relaunch loop: close the
    client, the queued command fires, the client comes back.

    Detached as well, so a slow or stuck invocation can't block the launch.
    """
    runtime.run(cfg, cfg.bnet_exe, [f'--exec={command}'], verbose=verbose,
                detach=True, verb="run", log=cfg.game_dir / "battlenet.log")


def launch_game(cfg: Config, product: str = D4_PRODUCT, verbose: bool = False,
                attempts: int = 3, base_wait: float = 25.0) -> bool:
    """Ask Battle.net to launch the game, retrying if it doesn't take.

    A single `--exec="launch Fen"` is famously unreliable: if the client was
    only just started, the first command is swallowed while it finishes
    initialising. Rather than making the user click twice, we issue the
    command and re-issue it if the game process hasn't appeared.

    The wait grows with each attempt. A swallowed command means the game will
    never appear, so sitting on a long timeout is pure dead time — but once a
    command has plausibly landed we want to be patient, because a cold start
    can take a while.
    """
    for attempt in range(1, attempts + 1):
        # Only the first command may start a client. `--exec` against a client
        # that is gone does not forward anything — it launches a whole new
        # Battle.net. Retrying blindly therefore resurrects a client the user
        # just closed, and closing it again simply triggers the next retry.
        if attempt > 1 and not procs.is_running(procs.BNET, cfg.prefix):
            log.error(
                "Battle.net is no longer running, so there is nothing to send "
                "the launch command to — stopping instead of starting it "
                "again. Run `d4l play` when you're ready."
            )
            return False

        log.info("Launching Diablo IV…" if attempt == 1 else
                 f"Retrying the launch ({attempt}/{attempts})…")
        exec_command(cfg, f"launch {product}", verbose=verbose)

        if procs.wait_for(procs.GAME, timeout=base_wait * attempt,
                          prefix=cfg.prefix):
            log.info("Diablo IV is running.")
            return True

        # The game may be up but not attributable to our prefix — Proton runs
        # it inside a container and the environment isn't always visible.
        # Detecting it by name is still better than relaunching on top of it.
        if procs.is_running(procs.GAME):
            log.warn("Diablo IV is running, but couldn't be tied to this "
                     "prefix — skipping automatic cleanup when it exits.")
            return True

        if attempt < attempts:
            log.warn("Game hasn't appeared yet; re-sending the launch command.")

    log.error(
        "Diablo IV did not start. It may need updating — the Battle.net "
        "window is open, so you can start it from there."
    )
    return False


def install_game(cfg: Config, product: str = D4_PRODUCT, verbose: bool = False) -> None:
    """Open Battle.net's install flow for the game."""
    if not start_client(cfg, verbose=verbose):
        return
    log.info("Opening the Diablo IV install page in Battle.net…")
    exec_command(cfg, f"install {product}", verbose=verbose)
