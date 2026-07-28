"""Configuration and filesystem layout for d4l."""

from __future__ import annotations

import json
import os
from pathlib import Path

APP = "battlenet-launcher4linux"
APP_NAME = "Battle.net Launcher4Linux"

# The project was called d4-launcher before it grew up into a Battle.net
# launcher. Settings are migrated from the old location on first run so a
# rename never silently loses someone's game_dir.
LEGACY_APP = "d4-launcher"

# Battle.net's internal product code for Diablo IV (codename "Fenris").
D4_PRODUCT = "Fen"

BNET_INSTALLER_URL = (
    "https://www.battle.net/download/getInstallerForGame"
    "?os=win&gameProgram=BATTLENET_APP&version=Live"
)


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default)


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / APP
STATE_DIR = _xdg("XDG_STATE_HOME", ".local/state") / APP
CONFIG_FILE = CONFIG_DIR / "config.json"
LOG_FILE = STATE_DIR / "bnl4l.log"

LEGACY_CONFIG_FILE = _xdg("XDG_CONFIG_HOME", ".config") / LEGACY_APP / "config.json"


def distro() -> str:
    """The running distribution's name, for the window subtitle."""
    try:
        with open("/etc/os-release") as fh:
            fields = dict(
                line.rstrip("\n").split("=", 1) for line in fh if "=" in line
            )
    except OSError:
        return "LINUX"
    name = (fields.get("NAME") or fields.get("PRETTY_NAME") or "Linux")
    return name.strip().strip('"').upper()

DEFAULTS = {
    "version": 1,
    # Everything the game needs lives under here: the Wine prefix, the
    # downloaded Battle.net installer, and (inside the prefix) the ~90 GB of
    # Diablo IV itself. Point this at another drive if $HOME is small.
    "game_dir": str(Path.home() / "Games" / "diablo4"),
    # "GE-Proton" tells umu to fetch and use the latest GE-Proton build.
    # Can also be an absolute path to a Proton directory.
    "proton": "GE-Proton",
    "gameid": "umu-default",
    "store": "none",
    # Delete the previous Proton build when switching versions. Off by
    # default: the usual reason to switch is a regression, and keeping the
    # last known-good build makes rolling back instant instead of a
    # re-download. See README.
    "prune_old_proton": False,
    # What Battle.net does with its own window when a game starts:
    # "keep", "minimize", "close", or "" to leave the client's own setting
    # untouched. Defaults to keeping it open — the client is the user's to
    # manage, and one that exits mid-launch takes the target of our --exec
    # commands with it.
    "battlenet_on_game_launch": "keep",
    # Leave the client running after the game exits; closing it is the
    # user's call, not ours.
    "close_battlenet_after_exit": False,
    "disable_bnet_hardware_accel": True,
    # Close the launcher window once Battle.net is up. The client doesn't
    # need us after that — nothing is supervising it.
    "close_gui_after_launch": False,
    # Wrappers
    "gamemode": False,
    "mangohud": False,
    # GPU features
    "nvidia_dlss": True,
    "raytracing": False,
    # Escape hatches
    "env": {},
    "launch_args": [],
    "skip_runtime_update": False,
}


class Config(dict):
    """Config dict with derived paths."""

    @property
    def game_dir(self) -> Path:
        return Path(os.path.expanduser(self["game_dir"])).resolve()

    @property
    def prefix(self) -> Path:
        return self.game_dir / "prefix"

    @property
    def wine_prefix(self) -> Path:
        """The real Wine prefix, which is not always `prefix` itself.

        What we hand umu as WINEPREFIX becomes Proton's compat-data
        directory, and Proton then builds the actual prefix in `pfx/`
        underneath it — so drive_c lives at `<prefix>/pfx/drive_c`. Plain
        Wine puts it directly in `<prefix>/drive_c`. Detect rather than
        assume, so both layouts work.
        """
        nested = self.prefix / "pfx"
        try:
            # umu points pfx at the prefix itself (pfx -> .); only treat it as
            # nested when it is genuinely a different directory.
            if (nested / "drive_c").is_dir() and nested.resolve() != self.prefix.resolve():
                return nested
        except OSError:
            pass
        return self.prefix

    @property
    def drive_c(self) -> Path:
        return self.wine_prefix / "drive_c"

    @property
    def installer(self) -> Path:
        return self.game_dir / "Battle.net-Setup.exe"

    @property
    def bnet_exe(self) -> Path:
        return self.drive_c / "Program Files (x86)" / "Battle.net" / "Battle.net.exe"

    @property
    def bnet_config(self) -> Path:
        """%APPDATA%/Battle.net/Battle.net.config inside the prefix."""
        users = self.drive_c / "users"
        for user in (users / "steamuser", users / os.environ.get("USER", "steamuser")):
            cfg = user / "AppData" / "Roaming" / "Battle.net" / "Battle.net.config"
            if cfg.exists():
                return cfg
        return users / "steamuser" / "AppData" / "Roaming" / "Battle.net" / "Battle.net.config"

    def find_game_exe(self) -> Path | None:
        """Locate Diablo IV.exe; the user may have installed it anywhere.

        Depth-bounded on purpose: a bare rglob here would walk the whole
        ~90 GB install on every status check.
        """
        drive_c = self.drive_c
        if not drive_c.is_dir():
            return None
        default = drive_c / "Program Files (x86)" / "Diablo IV" / "Diablo IV.exe"
        if default.exists():
            return default
        for depth in ("*", "*/*", "*/*/*"):
            for hit in drive_c.glob(f"{depth}/Diablo IV/Diablo IV.exe"):
                return hit
        return None

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(dict(self), indent=2) + "\n")
        tmp.replace(CONFIG_FILE)


def load() -> Config:
    cfg = Config(DEFAULTS)

    # Prefer the current location; fall back to the pre-rename one so an
    # upgrade keeps the user's settings — losing game_dir would point the
    # launcher at an empty directory and look exactly like a broken install.
    source = CONFIG_FILE if CONFIG_FILE.exists() else LEGACY_CONFIG_FILE
    migrating = source is LEGACY_CONFIG_FILE and source.exists()

    if source.exists():
        try:
            user = json.loads(source.read_text())
            if isinstance(user, dict):
                cfg.update(user)
        except (json.JSONDecodeError, OSError):
            # A corrupt config should never block launching the game.
            migrating = False

    if migrating:
        try:
            cfg.save()
        except OSError:
            pass
    return cfg
