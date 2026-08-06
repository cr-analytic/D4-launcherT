"""Argument parsing and the two front-ends: Tk window, or a console fallback."""

from __future__ import annotations

import argparse
import sys
import time

from . import power
from .nvml import NvmlError, open_source
from .power import CONNECTORS, Status
from .sampler import Sampler

ANSI = {
    Status.NOMINAL: "\033[32m",
    Status.ELEVATED: "\033[33m",
    Status.HIGH: "\033[38;5;208m",
    Status.CRITICAL: "\033[31m",
}
RESET = "\033[0m"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pinwatch",
        description="Live 12VHPWR load monitor: board watts -> connector amps -> per-pin load.",
    )
    p.add_argument("-g", "--gpu", type=int, default=0, help="GPU index (default: 0)")
    p.add_argument(
        "-i", "--interval", type=float, default=0.25,
        help="seconds between samples (default: 0.25)",
    )
    p.add_argument(
        "-c", "--connector", choices=sorted(CONNECTORS), default="12vhpwr",
        help="connector to model (default: 12vhpwr)",
    )
    p.add_argument(
        "-v", "--volts", type=float, default=power.NOMINAL_VOLTS,
        help="rail voltage used for the P=VI conversion (default: 12.0)",
    )
    p.add_argument(
        "-s", "--slot-watts", type=float, default=0.0,
        help="watts to attribute to the PCIe slot rather than the connector "
             "(default: 0, i.e. worst case)",
    )
    p.add_argument(
        "--share", type=float, default=None,
        help="percent of total current on the worst pin; default is perfect balance",
    )
    p.add_argument(
        "--contact-mohm", type=float, default=power.DEFAULT_CONTACT_MOHM,
        help="per-terminal contact resistance for the dissipation estimate "
             f"(default: {power.DEFAULT_CONTACT_MOHM:g})",
    )
    p.add_argument("--history", type=int, default=480, help="samples kept for the graph")
    p.add_argument("--console", action="store_true", help="text output instead of the GUI")
    p.add_argument("--once", action="store_true", help="print a single reading and exit")
    return p


def _line(load: power.Load, sample) -> str:
    colour = ANSI[load.status] if sys.stdout.isatty() else ""
    reset = RESET if colour else ""
    temp = f"  {sample.temp_c:.0f}°C" if sample.temp_c is not None else ""
    return (
        f"{load.connector_w:7.1f} W  {load.total_a:6.2f} A  "
        f"{colour}{load.worst_pin_a:5.2f} A/pin  "
        f"{load.pct_of_terminal:3.0f}% of {load.conn.pin_rating_a:.1f} A  "
        f"{load.status.value:<8}{reset}{temp}"
    )


def run_console(sampler: Sampler, info, opts) -> int:
    conn = CONNECTORS[opts.connector]
    print(f"{info.name} · driver {info.driver} · {info.backend}")
    print(
        f"{conn.label}: {conn.pins} x 12V pins, {conn.pin_rating_a:.1f} A per terminal, "
        f"{conn.rated_w:.0f} W rated "
        f"({conn.spec_pin_a:.2f} A/pin at rating, {conn.design_margin:.2f}x margin)"
    )
    print()
    try:
        while True:
            sample, error = sampler.latest()
            if sample is None:
                if error and opts.once:
                    print(f"error: {error}", file=sys.stderr)
                    return 1
                time.sleep(opts.interval)
                continue
            load = power.compute(
                sample.watts, conn=conn, volts=opts.volts, slot_w=opts.slot_watts,
                share=None if opts.share is None else opts.share / 100.0,
                contact_mohm=opts.contact_mohm,
            )
            if opts.once:
                print(_line(load, sample))
                return 0
            print(_line(load, sample), flush=True)
            time.sleep(opts.interval)
    except KeyboardInterrupt:
        print(f"\npeak {sampler.peak_w:.1f} W = {sampler.peak_w / opts.volts:.2f} A")
        return 0


def main(argv: list[str] | None = None) -> int:
    opts = build_parser().parse_args(argv)
    if opts.interval <= 0:
        print("error: --interval must be positive", file=sys.stderr)
        return 2
    if opts.share is not None and not 0 < opts.share <= 100:
        print("error: --share must be a percentage in (0, 100]", file=sys.stderr)
        return 2

    try:
        source = open_source(opts.gpu)
        info = source.describe()
    except NvmlError as exc:
        print(f"error: no usable NVIDIA power source.\n{exc}", file=sys.stderr)
        return 1

    if not power.is_50_series(info.name):
        print(
            f"note: {info.name} is not an RTX 50-series card; the 12VHPWR model "
            "may not describe how it is actually powered.",
            file=sys.stderr,
        )

    sampler = Sampler(source, interval_s=opts.interval, history=opts.history).start()

    if opts.console or opts.once:
        try:
            return run_console(sampler, info, opts)
        finally:
            sampler.stop()

    try:
        from .gui import App
    except ImportError as exc:
        print(
            f"error: Tk is unavailable ({exc}).\n"
            "Install it (Debian/Ubuntu: python3-tk, Fedora: python3-tkinter, "
            "Arch: tk) or run with --console.",
            file=sys.stderr,
        )
        sampler.stop()
        return 1

    App(
        sampler,
        info,
        conn=CONNECTORS[opts.connector],
        volts=opts.volts,
        slot_w=opts.slot_watts,
        contact_mohm=opts.contact_mohm,
    ).run()
    return 0
