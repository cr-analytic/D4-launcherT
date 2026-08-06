"""Watts -> amps -> per-pin load, plus the thresholds that make it meaningful.

All of this is derived from the connector spec rather than hard-coded magic
numbers, so swapping the connector rewrites the thresholds correctly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

NOMINAL_VOLTS = 12.0


@dataclass(frozen=True)
class Connector:
    key: str
    label: str
    pins: int  # 12V conductors (grounds carry the return, same current)
    pin_rating_a: float  # continuous per-terminal rating from the terminal spec
    rated_w: float  # connector's rated power delivery

    @property
    def spec_pin_a(self) -> float:
        """Per-pin current at the connector's rated wattage, perfectly balanced."""
        return self.rated_w / NOMINAL_VOLTS / self.pins

    @property
    def design_margin(self) -> float:
        """Terminal rating over spec-max load. 12VHPWR ships with ~1.14x."""
        return self.pin_rating_a / self.spec_pin_a


# 12VHPWR and 12V-2x6 are electrically identical — 6x 12V + 6x ground, Molex
# Micro-Fit+ terminals rated 9.5 A each. 2x6 only changes the sense-pin depth.
CONNECTORS = {
    "12vhpwr": Connector("12vhpwr", "12VHPWR (12+4)", 6, 9.5, 600.0),
    "12v-2x6": Connector("12v-2x6", "12V-2x6", 6, 9.5, 600.0),
    "pcie8": Connector("pcie8", "PCIe 8-pin", 3, 8.0, 150.0),
    "pcie6": Connector("pcie6", "PCIe 6-pin", 2, 8.0, 75.0),
}

DEFAULT_CONNECTOR = CONNECTORS["12vhpwr"]

# Terminal contact resistance dominates the heat at the connector; 5 mOhm is a
# reasonable healthy-contact figure. A degraded or partly-seated pin runs far
# higher, which is exactly how these connectors fail.
DEFAULT_CONTACT_MOHM = 5.0


class Status(Enum):
    NOMINAL = "nominal"
    ELEVATED = "elevated"
    HIGH = "high"
    CRITICAL = "critical"


#: Fraction of the connector's spec-max per-pin current at which each band starts.
BAND_EDGES = ((Status.NOMINAL, 0.60), (Status.ELEVATED, 1.00))


def classify(pin_a: float, conn: Connector) -> Status:
    """Band a per-pin current: nominal / elevated / high / critical."""
    if pin_a > conn.pin_rating_a:
        return Status.CRITICAL  # past the terminal's own rating
    ratio = pin_a / conn.spec_pin_a
    for status, edge in BAND_EDGES:
        if ratio <= edge:
            return status
    return Status.HIGH  # above spec-max load but still under terminal rating


@dataclass(frozen=True)
class Load:
    """A power reading resolved into connector currents."""

    board_w: float
    connector_w: float
    total_a: float
    ideal_pin_a: float
    worst_pin_a: float
    worst_pin_w: float  # estimated dissipation in that terminal
    status: Status
    conn: Connector
    volts: float
    share: float

    @property
    def pct_of_terminal(self) -> float:
        return 100.0 * self.worst_pin_a / self.conn.pin_rating_a

    @property
    def pct_of_rated_w(self) -> float:
        return 100.0 * self.connector_w / self.conn.rated_w

    @property
    def balanced(self) -> bool:
        return abs(self.share - 1.0 / self.conn.pins) < 1e-9


def compute(
    board_w: float,
    conn: Connector = DEFAULT_CONNECTOR,
    volts: float = NOMINAL_VOLTS,
    slot_w: float = 0.0,
    share: float | None = None,
    contact_mohm: float = DEFAULT_CONTACT_MOHM,
) -> Load:
    """Resolve a board-power reading into connector current and per-pin load.

    ``board_w`` is whole-board power as the driver reports it. ``slot_w`` is how
    much of that you attribute to the PCIe slot; it defaults to 0 so the
    connector figures stay worst-case unless you say otherwise.

    ``share`` is the fraction of total current on the worst pin. It defaults to
    ``1/pins`` (perfect balance) — that is the *theoretical* case, not a
    measured one. Nothing here can detect real imbalance; see README.
    """
    if volts <= 0:
        raise ValueError("volts must be positive")
    if share is not None and not 0 < share <= 1:
        raise ValueError("share must be within (0, 1]")

    share = 1.0 / conn.pins if share is None else share
    connector_w = max(0.0, board_w - slot_w)
    total_a = connector_w / volts
    worst_pin_a = total_a * share

    return Load(
        board_w=board_w,
        connector_w=connector_w,
        total_a=total_a,
        ideal_pin_a=total_a / conn.pins,
        worst_pin_a=worst_pin_a,
        worst_pin_w=worst_pin_a**2 * (contact_mohm / 1000.0),
        status=classify(worst_pin_a, conn),
        conn=conn,
        volts=volts,
        share=share,
    )


def is_50_series(name: str) -> bool:
    """True for RTX 50-series marketing names (5050 through 5090, incl. Ti/Super)."""
    tokens = name.upper().replace("-", " ").split()
    return any(
        t[:2] == "50" and len(t) == 4 and t.isdigit() and t != "5000" for t in tokens
    )
