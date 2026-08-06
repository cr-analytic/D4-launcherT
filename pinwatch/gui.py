"""Tk GUI. Stdlib only — on most distros that means installing python3-tk."""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont

from . import power
from .nvml import DeviceInfo
from .power import Connector, Status
from .sampler import Sampler

BG = "#12141a"
PANEL = "#1a1d26"
EDGE = "#272b38"
TEXT = "#e8eaf0"
MUTED = "#7d8598"

STATUS_COLOR = {
    Status.NOMINAL: "#3ddc84",
    Status.ELEVATED: "#ffd23f",
    Status.HIGH: "#ff8c42",
    Status.CRITICAL: "#ff4d4d",
}
STATUS_TEXT = {
    Status.NOMINAL: "NOMINAL",
    Status.ELEVATED: "ELEVATED",
    Status.HIGH: "HIGH — above spec-max per-pin load",
    Status.CRITICAL: "CRITICAL — above terminal rating",
}


class App:
    def __init__(
        self,
        sampler: Sampler,
        info: DeviceInfo,
        conn: Connector = power.DEFAULT_CONNECTOR,
        volts: float = power.NOMINAL_VOLTS,
        slot_w: float = 0.0,
        contact_mohm: float = power.DEFAULT_CONTACT_MOHM,
        refresh_ms: int = 200,
    ):
        self.sampler = sampler
        self.info = info
        self.conn = conn
        self.volts = volts
        self.slot_w = slot_w
        self.contact_mohm = contact_mohm
        self.refresh_ms = refresh_ms

        self.root = tk.Tk()
        self.root.title("pinwatch — 12VHPWR load monitor")
        self.root.configure(bg=BG)
        self.root.minsize(520, 620)

        self.mono = tkfont.nametofont("TkFixedFont").actual("family")
        self.sans = tkfont.nametofont("TkDefaultFont").actual("family")

        self._build_header()
        self._build_readouts()
        self._build_status()
        self._build_pins()
        self._build_graph()
        self._build_imbalance()
        self._build_footer()

        # Whatever the font and DPI work out to, don't let the window shrink
        # below the height its own content needs.
        self.root.update_idletasks()
        self.root.minsize(520, self.root.winfo_reqheight())

        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        self.root.bind("<Escape>", lambda _e: self._quit())
        self.root.bind("r", lambda _e: self.sampler.reset_peak())
        self._tick()

    # ---------------------------------------------------------------- layout

    def _panel(self, **kw) -> tk.Frame:
        frame = tk.Frame(self.root, bg=PANEL, highlightbackground=EDGE, highlightthickness=1)
        frame.pack(fill="x", padx=12, **kw)
        return frame

    def _build_header(self) -> None:
        head = self._panel(pady=(12, 6))
        warn = "" if power.is_50_series(self.info.name) else "  (not a 50-series card)"
        tk.Label(
            head,
            text=self.info.name + warn,
            bg=PANEL,
            fg=TEXT,
            font=(self.sans, 12, "bold"),
            anchor="w",
        ).pack(fill="x", padx=12, pady=(8, 0))

        limit = f"{self.info.limit_w:.0f} W limit" if self.info.limit_w else "limit n/a"
        tk.Label(
            head,
            text=f"driver {self.info.driver}  ·  gpu {self.info.index}  ·  "
            f"{limit}  ·  {self.info.backend}  ·  {self.conn.label}",
            bg=PANEL,
            fg=MUTED,
            font=(self.sans, 9),
            anchor="w",
        ).pack(fill="x", padx=12, pady=(2, 8))

    def _build_readouts(self) -> None:
        row = self._panel(pady=6)
        self.readouts = {}
        for i, (key, caption) in enumerate(
            (("w", "board power"), ("a", "connector current"), ("pin", "per pin"))
        ):
            cell = tk.Frame(row, bg=PANEL)
            cell.grid(row=0, column=i, sticky="nsew", pady=12)
            row.grid_columnconfigure(i, weight=1, uniform="readout")

            value = tk.Label(cell, text="—", bg=PANEL, fg=TEXT, font=(self.mono, 26, "bold"))
            value.pack()
            unit = tk.Label(cell, text="", bg=PANEL, fg=MUTED, font=(self.sans, 9))
            unit.pack()
            tk.Label(cell, text=caption, bg=PANEL, fg=MUTED, font=(self.sans, 8)).pack()
            self.readouts[key] = (value, unit)

    def _build_status(self) -> None:
        bar = self._panel(pady=6)
        self.status_label = tk.Label(
            bar, text="waiting for first sample", bg=PANEL, fg=MUTED,
            font=(self.sans, 11, "bold"),
        )
        self.status_label.pack(pady=8)
        self.status_bar = tk.Canvas(bar, height=8, bg=PANEL, highlightthickness=0)
        self.status_bar.pack(fill="x", padx=12, pady=(0, 12))

    def _build_pins(self) -> None:
        box = self._panel(pady=6)
        tk.Label(
            box, text="THEORETICAL PER-PIN CURRENT", bg=PANEL, fg=MUTED,
            font=(self.sans, 8, "bold"), anchor="w",
        ).pack(fill="x", padx=12, pady=(8, 0))
        self.pin_canvas = tk.Canvas(box, height=78, bg=PANEL, highlightthickness=0)
        self.pin_canvas.pack(fill="x", padx=12, pady=(4, 10))

    def _build_graph(self) -> None:
        box = self._panel(pady=6)
        tk.Label(
            box, text="HISTORY", bg=PANEL, fg=MUTED, font=(self.sans, 8, "bold"), anchor="w"
        ).pack(fill="x", padx=12, pady=(8, 0))
        self.graph = tk.Canvas(box, height=120, bg=PANEL, highlightthickness=0)
        self.graph.pack(fill="x", padx=12, pady=(4, 10))

    def _build_imbalance(self) -> None:
        box = self._panel(pady=6)
        tk.Label(
            box, text="IMBALANCE MODEL — what if one pin carries more?",
            bg=PANEL, fg=MUTED, font=(self.sans, 8, "bold"), anchor="w",
        ).pack(fill="x", padx=12, pady=(8, 0))

        # The scale quantises to 0.1, so 100/6 comes back as 16.7. Snap anything
        # at the low stop back to exactly 1/pins, else "balanced" never holds.
        self._ideal_share_pct = round(100.0 / self.conn.pins, 1)
        self.share_var = tk.DoubleVar(value=self._ideal_share_pct)
        scale = tk.Scale(
            box,
            from_=self._ideal_share_pct,
            to=min(95.0, round(100.0 / self.conn.pins * 3.6, 1)),
            resolution=0.1,
            orient="horizontal",
            variable=self.share_var,
            bg=PANEL,
            fg=TEXT,
            troughcolor=BG,
            highlightthickness=0,
            activebackground=TEXT,
            font=(self.mono, 8),
            label="share of total current on the worst pin (%)",
        )
        scale.pack(fill="x", padx=12)
        self.imbalance_label = tk.Label(
            box, text="", bg=PANEL, fg=MUTED, font=(self.mono, 9), anchor="w", justify="left"
        )
        self.imbalance_label.pack(fill="x", padx=12, pady=(0, 10))
        # Wrap to the panel instead of clipping. Only reconfigure on an actual
        # width change, or the resulting height change re-triggers this forever.
        self._wrap_at = 0
        self.imbalance_label.bind("<Configure>", self._rewrap)

    def _rewrap(self, event) -> None:
        if event.width != self._wrap_at:
            self._wrap_at = event.width
            self.imbalance_label.config(wraplength=event.width)

    def _build_footer(self) -> None:
        foot = tk.Frame(self.root, bg=BG)
        foot.pack(fill="x", padx=12, pady=(6, 12))
        self.footer = tk.Label(
            foot, text="", bg=BG, fg=MUTED, font=(self.mono, 8), anchor="w", justify="left"
        )
        self.footer.pack(side="left")
        tk.Button(
            foot, text="reset peak", command=self.sampler.reset_peak, bg=PANEL, fg=TEXT,
            activebackground=EDGE, activeforeground=TEXT, relief="flat",
            font=(self.sans, 8), padx=10,
        ).pack(side="right")

    # ----------------------------------------------------------------- paint

    def _share(self) -> float | None:
        """Slider position as a fraction, or None when it sits at perfect balance."""
        pct = self.share_var.get()
        return None if pct <= self._ideal_share_pct else pct / 100.0

    def _tick(self) -> None:
        sample, error = self.sampler.latest()
        if sample is None:
            self.status_label.config(
                text=error or "waiting for first sample",
                fg=STATUS_COLOR[Status.CRITICAL] if error else MUTED,
            )
        else:
            load = power.compute(
                sample.watts,
                conn=self.conn,
                volts=self.volts,
                slot_w=self.slot_w,
                share=self._share(),
                contact_mohm=self.contact_mohm,
            )
            self._paint_readouts(load, sample)
            self._paint_status(load, error)
            self._paint_pins(load)
            self._paint_imbalance(load)
            self._paint_footer(load, sample)
        self._paint_graph()
        self.root.after(self.refresh_ms, self._tick)

    def _paint_readouts(self, load: power.Load, sample) -> None:
        colour = STATUS_COLOR[load.status]
        watts, unit_w = self.readouts["w"]
        watts.config(text=f"{load.board_w:6.1f}")
        label = "W instant" if sample.instant else "W average"
        if self.slot_w:
            label += f" → {load.connector_w:.0f} W connector"
        unit_w.config(text=label)

        amps, unit_a = self.readouts["a"]
        amps.config(text=f"{load.total_a:6.2f}", fg=colour)
        unit_a.config(text=f"A @ {load.volts:.1f} V")

        pin, unit_pin = self.readouts["pin"]
        pin.config(text=f"{load.worst_pin_a:6.2f}", fg=colour)
        unit_pin.config(
            text=f"A across {self.conn.pins} pins"
            if load.balanced
            else f"A worst of {self.conn.pins}"
        )

    def _paint_status(self, load: power.Load, error: str | None) -> None:
        colour = STATUS_COLOR[load.status]
        text = STATUS_TEXT[load.status]
        if error:
            text += "  ·  driver read failing, showing last good sample"
        self.status_label.config(text=text, fg=colour)

        bar = self.status_bar
        bar.delete("all")
        width = bar.winfo_width() or 1
        # Full bar = the terminal rating; the tick marks spec-max load.
        frac = min(1.0, load.worst_pin_a / self.conn.pin_rating_a)
        bar.create_rectangle(0, 0, width, 8, fill=BG, outline="")
        bar.create_rectangle(0, 0, width * frac, 8, fill=colour, outline="")
        spec_x = width * (self.conn.spec_pin_a / self.conn.pin_rating_a)
        bar.create_line(spec_x, 0, spec_x, 8, fill=TEXT, width=1)

    def _paint_pins(self, load: power.Load) -> None:
        canvas = self.pin_canvas
        canvas.delete("all")
        width = canvas.winfo_width() or 1
        n = self.conn.pins
        slot = width / n
        # With perfect balance every pin is identical; under the imbalance model
        # pin 1 takes the elevated share and the rest split what remains.
        others = (load.total_a - load.worst_pin_a) / (n - 1) if n > 1 else 0.0

        for i in range(n):
            amps = load.worst_pin_a if i == 0 else others
            colour = STATUS_COLOR[power.classify(amps, self.conn)]
            cx = slot * (i + 0.5)
            r = max(12.0, min(20.0, slot * 0.28))  # room for "15.4" at 2 digits
            canvas.create_oval(
                cx - r, 12, cx + r, 12 + 2 * r, fill=colour if amps > 0 else BG,
                outline=EDGE, width=1,
            )
            canvas.create_text(
                cx, 12 + r, text=f"{amps:.1f}", fill=BG if amps > 0 else MUTED,
                font=(self.mono, 9, "bold"),
            )
            canvas.create_text(
                cx, 62, text=f"pin {i + 1}" + ("" if load.balanced or i else " ▲"),
                fill=MUTED, font=(self.sans, 7),
            )

    def _paint_graph(self) -> None:
        canvas = self.graph
        canvas.delete("all")
        width = canvas.winfo_width() or 1
        height = canvas.winfo_height() or 1
        history = self.sampler.history()
        if len(history) < 2:
            canvas.create_text(
                width / 2, height / 2, text="collecting…", fill=MUTED, font=(self.sans, 9)
            )
            return

        ceiling = max(self.sampler.peak_w, self.info.limit_w or 0.0, 1.0) * 1.1
        capacity = self.sampler.capacity or len(history)

        def x_of(i: int) -> float:
            return width * i / max(1, capacity - 1)

        def y_of(w: float) -> float:
            return height - (height - 4) * min(1.0, w / ceiling)

        if self.info.limit_w:
            y = y_of(self.info.limit_w)
            canvas.create_line(0, y, width, y, fill=EDGE, dash=(4, 3))
            canvas.create_text(
                width - 4, y - 7, text=f"{self.info.limit_w:.0f} W limit", anchor="e",
                fill=MUTED, font=(self.sans, 7),
            )

        points = []
        for i, (_t, watts) in enumerate(history):
            points.extend((x_of(i), y_of(watts)))
        colour = STATUS_COLOR[
            power.compute(
                history[-1][1], conn=self.conn, volts=self.volts, slot_w=self.slot_w,
                share=self._share(),
            ).status
        ]
        canvas.create_polygon(
            [0, height, *points, x_of(len(history) - 1), height],
            fill=colour, outline="", stipple="gray25",
        )
        canvas.create_line(points, fill=colour, width=2, smooth=False)

        peak_y = y_of(self.sampler.peak_w)
        canvas.create_line(0, peak_y, width, peak_y, fill=MUTED, dash=(2, 4))
        canvas.create_text(
            4, peak_y - 7,
            text=f"peak {self.sampler.peak_w:.0f} W = {self.sampler.peak_w / self.volts:.1f} A",
            anchor="w", fill=MUTED, font=(self.sans, 7),
        )

    def _paint_imbalance(self, load: power.Load) -> None:
        if load.balanced:
            note = (
                f"perfectly balanced: {load.ideal_pin_a:.2f} A per pin, "
                f"{load.pct_of_terminal:.0f}% of the {self.conn.pin_rating_a:.1f} A terminal rating"
            )
        else:
            note = (
                f"worst pin {load.worst_pin_a:.2f} A "
                f"({load.pct_of_terminal:.0f}% of {self.conn.pin_rating_a:.1f} A rating)  ·  "
                f"~{load.worst_pin_w:.2f} W dissipated in that terminal "
                f"at {self.contact_mohm:.0f} mΩ contact resistance"
            )
        self.imbalance_label.config(text=note, fg=STATUS_COLOR[load.status])

    def _paint_footer(self, load: power.Load, sample) -> None:
        peak_a = self.sampler.peak_w / self.volts
        bits = [
            f"peak {self.sampler.peak_w:6.1f} W = {peak_a:5.2f} A = "
            f"{peak_a / self.conn.pins:5.2f} A/pin",
            f"connector at {load.pct_of_rated_w:.0f}% of its {self.conn.rated_w:.0f} W rating",
        ]
        if sample.temp_c is not None:
            bits.append(f"gpu {sample.temp_c:.0f} °C")
        if self.slot_w:
            bits.append(f"slot offset −{self.slot_w:.0f} W")
        bits.append(f"{self.sampler.samples} samples in {self.sampler.uptime_s:.0f} s")
        self.footer.config(text="\n".join(bits))

    # ------------------------------------------------------------------ life

    def _quit(self) -> None:
        self.sampler.stop()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
