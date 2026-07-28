"""Finding and stopping Wine processes belonging to our prefix.

Matching is done on /proc/<pid>/comm rather than the full command line: Wine
sets comm to the Windows executable name, and comm-matching avoids the obvious
false positive of `umu-run .../Battle.net.exe`, whose *cmdline* also contains
the exe name but which is not the game.

The kernel truncates comm to 15 characters (TASK_COMM_LEN - 1), so all
comparisons are made against the truncated form.
"""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

COMM_MAX = 15

BNET = "Battle.net.exe"
BNET_HELPER = "Battle.net Helper.exe"
BNET_AGENT = "Agent.exe"
GAME = "Diablo IV.exe"

# Processes to clean up once the game has exited.
LEFTOVERS = (BNET, BNET_HELPER, BNET_AGENT, "Battle.net Launcher.exe")


# Variables that identify which Wine prefix a process belongs to. umu sets
# WINEPREFIX; Proton derives its own from STEAM_COMPAT_DATA_PATH, so both are
# checked.
PREFIX_VARS = ("WINEPREFIX", "STEAM_COMPAT_DATA_PATH", "PROTONPREFIX")


def _comm(name: str) -> str:
    return name[:COMM_MAX]


def _environ(pid: int) -> dict | None:
    """A process's environment, or None if we can't read it."""
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return None
    env = {}
    for item in raw.split(b"\0"):
        if b"=" in item:
            key, _, value = item.partition(b"=")
            try:
                env[key.decode()] = value.decode()
            except UnicodeDecodeError:
                continue
    return env


def in_prefix(pid: int, prefix) -> bool:
    """Whether `pid` belongs to the given Wine prefix.

    Battle.net may legitimately be running for another game in a different
    prefix — a Lutris WoW install, say. Killing that on our way out would be
    a nasty surprise, so anything we terminate has to be provably ours.
    Processes whose environment we cannot read are treated as *not* ours:
    leaving a stray process behind is much cheaper than killing someone
    else's session.
    """
    env = _environ(pid)
    if env is None:
        return False
    # Compare resolved paths: the prefix may be reached through a symlink or
    # bind mount on one side and not the other, and umu leaves a `pfx -> .`
    # inside the prefix that shows up in some of these variables.
    target = os.path.realpath(str(prefix)).rstrip("/")
    for var in PREFIX_VARS:
        raw = env.get(var)
        if not raw:
            continue
        for value in (raw.rstrip("/"), os.path.realpath(raw).rstrip("/")):
            if value == target or value.startswith(target + "/"):
                return True
    return False


def is_running_anywhere(name: str) -> bool:
    """Whether any process of this name exists, in any prefix.

    Detection is deliberately more forgiving than termination. Proton runs
    the game inside a container and /proc/<pid>/environ is not always
    readable or meaningful, so a client we cannot attribute may still be
    ours — and starting a second one, or relaunching over a running game,
    is worse than briefly considering someone else's process. Anything that
    *kills* still demands positive attribution.
    """
    return bool(pids_named(name))


def pids_named(name: str, prefix=None) -> list[int]:
    """PIDs whose comm matches the (truncated) executable name.

    With `prefix`, only processes belonging to that Wine prefix are returned.
    """
    want = _comm(name)
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if (entry / "comm").read_text().strip() != want:
                continue
        except (OSError, ValueError):
            continue  # process exited from under us
        pid = int(entry.name)
        if prefix is None or in_prefix(pid, prefix):
            found.append(pid)
    return found


def is_running(name: str, prefix=None) -> bool:
    return bool(pids_named(name, prefix))


def wait_for(name: str, timeout: float, interval: float = 0.5, prefix=None) -> bool:
    """Block until a process named `name` appears, or `timeout` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_running(name, prefix):
            return True
        time.sleep(interval)
    return False


def wait_while(name: str, interval: float = 2.0, prefix=None) -> None:
    """Block for as long as any process named `name` is alive."""
    while is_running(name, prefix):
        time.sleep(interval)


def terminate(names=LEFTOVERS, grace: float = 8.0, prefix=None) -> int:
    """SIGTERM the named processes, then SIGKILL whatever refuses to go.

    Pass `prefix` to confine this to one Wine prefix — see `in_prefix`.
    """
    pids = [pid for name in names for pid in pids_named(name, prefix)]
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass

    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not any(Path(f"/proc/{pid}").exists() for pid in pids):
            return len(pids)
        time.sleep(0.4)

    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    return len(pids)
