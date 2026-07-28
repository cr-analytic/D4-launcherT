"""Tiny status logger: one line to the terminal, the same line to the log file."""

from __future__ import annotations

import datetime
import sys

from .config import LOG_FILE, STATE_DIR

# Set by the GUI so progress shows up in the window instead of a terminal.
sink = None


def _write_file(line: str) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a") as fh:
            fh.write(f"{stamp}  {line}\n")
    except OSError:
        pass


def info(msg: str) -> None:
    print(f"==> {msg}", flush=True)
    _write_file(msg)
    if sink:
        sink(msg)


def warn(msg: str) -> None:
    print(f"  ! {msg}", file=sys.stderr, flush=True)
    _write_file(f"WARN {msg}")
    if sink:
        sink(msg)


def error(msg: str) -> None:
    print(f"  ✗ {msg}", file=sys.stderr, flush=True)
    _write_file(f"ERROR {msg}")
    if sink:
        sink(msg)
