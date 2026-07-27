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


def _comm(name: str) -> str:
    return name[:COMM_MAX]


def pids_named(name: str) -> list[int]:
    """PIDs whose comm matches the (truncated) executable name."""
    want = _comm(name)
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if (entry / "comm").read_text().strip() == want:
                found.append(int(entry.name))
        except (OSError, ValueError):
            continue  # process exited from under us
    return found


def is_running(name: str) -> bool:
    return bool(pids_named(name))


def wait_for(name: str, timeout: float, interval: float = 0.5) -> bool:
    """Block until a process named `name` appears, or `timeout` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_running(name):
            return True
        time.sleep(interval)
    return False


def wait_while(name: str, interval: float = 2.0) -> None:
    """Block for as long as any process named `name` is alive."""
    while is_running(name):
        time.sleep(interval)


def terminate(names=LEFTOVERS, grace: float = 8.0) -> int:
    """SIGTERM the named processes, then SIGKILL whatever refuses to go."""
    pids = [pid for name in names for pid in pids_named(name)]
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
