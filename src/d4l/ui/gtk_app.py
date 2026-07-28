"""A deliberately small GTK4/libadwaita launcher window.

One button that does the right thing depending on what is installed, a status
line, and nothing else. If PyGObject or libadwaita aren't available we say so
and point at the CLI rather than failing with a traceback.
"""

from __future__ import annotations

import sys
import threading

from .. import battlenet, config as cfgmod, doctor, game, log, procs, proton, runtime

CSS = b"""
.d4-title    { font-size: 30px; font-weight: 800; letter-spacing: 5px; }
.d4-subtitle { font-size: 12px; letter-spacing: 3px; opacity: 0.55; }
.d4-play     { font-size: 17px; font-weight: 700; padding: 14px 0; }
.d4-status   { font-size: 12px; opacity: 0.7; }
.d4-proton   { font-size: 11px; opacity: 0.6; letter-spacing: 1px; }
"""


def _missing(exc: Exception) -> int:
    print(
        f"d4l: the graphical launcher needs GTK4 and libadwaita ({exc}).\n"
        "     Install them with:  sudo pacman -S python-gobject libadwaita gtk4\n"
        "     Or just use the command line:  d4l play",
        file=sys.stderr,
    )
    return 1


def main(cfg: cfgmod.Config) -> int:
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango
    except (ImportError, ValueError) as exc:
        return _missing(exc)

    class Window(Adw.ApplicationWindow):
        def __init__(self, app):
            super().__init__(application=app, title="Diablo IV")
            self.set_default_size(400, 460)
            self.busy = False

            root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            header = Adw.HeaderBar(css_classes=["flat"])
            header.pack_end(self._menu())
            root.append(header)

            body = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL, spacing=14,
                valign=Gtk.Align.CENTER, vexpand=True,
                margin_start=36, margin_end=36, margin_bottom=28,
            )
            body.append(Gtk.Label(label="DIABLO IV", css_classes=["d4-title"]))
            body.append(Gtk.Label(label="CACHYOS", css_classes=["d4-subtitle"]))

            self.play = Gtk.Button(
                css_classes=["suggested-action", "pill", "d4-play"], margin_top=18)
            self.play.connect("clicked", self.on_play)
            body.append(self.play)

            self.spinner = Gtk.Spinner(margin_top=6)
            body.append(self.spinner)

            self.status = Gtk.Label(
                label="", css_classes=["d4-status"], wrap=True, lines=3,
                justify=Gtk.Justification.CENTER,
                ellipsize=Pango.EllipsizeMode.END, margin_top=2,
            )
            body.append(self.status)

            body.append(self._proton_picker())

            root.append(body)
            self.set_content(root)

            self.refresh()
            # Keep the button honest if the game is started or closed elsewhere.
            GLib.timeout_add_seconds(3, self.refresh)

        # -- Proton picker ---------------------------------------------
        def _proton_picker(self):
            """Proton version is the usual cause of Battle.net/D4 breakage, so
            it gets a control in the main window rather than a settings page."""
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                          margin_top=22)
            box.append(Gtk.Label(label="PROTON", css_classes=["d4-proton"],
                                 halign=Gtk.Align.CENTER))

            self.proton_values = []
            self.proton_drop = Gtk.DropDown(halign=Gtk.Align.CENTER)
            self.proton_drop.set_model(Gtk.StringList())
            self._reload_protons()
            self.proton_handler = self.proton_drop.connect(
                "notify::selected", self.on_proton_changed)
            box.append(self.proton_drop)
            return box

        def _reload_protons(self):
            """Repopulate the dropdown without firing the change handler.

            Cache-only: this runs on the UI thread, so it must never block on
            the network. `_refresh_protons` does the fetching from a worker.
            """
            try:
                pairs = proton.choices(network=False)
            except Exception:
                pairs = [(k, k) for k in proton.KEYWORDS]

            active = cfg["proton"]
            if not any(v == active for v, _ in pairs):
                pairs.insert(0, (active, f"{active} — current"))

            handler = getattr(self, "proton_handler", None)
            if handler:
                self.proton_drop.handler_block(handler)

            model = Gtk.StringList()
            self.proton_values = []
            for value, label in pairs:
                model.append(label)
                self.proton_values.append(value)
            self.proton_drop.set_model(model)
            self.proton_drop.set_selected(self.proton_values.index(active))

            if handler:
                self.proton_drop.handler_unblock(handler)

        def on_proton_changed(self, drop, _param):
            index = drop.get_selected()
            if index == Gtk.INVALID_LIST_POSITION or index >= len(self.proton_values):
                return
            chosen = self.proton_values[index]
            if chosen == cfg["proton"]:
                return
            if (procs.is_running_anywhere(procs.GAME)
                    or procs.is_running_anywhere(procs.BNET)):
                self.say("Close the game and Battle.net before switching Proton.")
                # Revert on the next main-loop pass: replacing the model from
                # inside its own notify::selected emission crashes GTK.
                GLib.idle_add(self._reload_protons)
                return
            self.run_bg(lambda: self._apply_proton(chosen))

        def _apply_proton(self, name):
            proton.use(cfg, name)
            GLib.idle_add(self._reload_protons)
            self.say(f"Proton set to {name}. Shader caches cleared — "
                     "the first launch will be slower while they rebuild.")

        def _refresh_protons(self):
            """Fetch the release list (worker thread), then update the model."""
            tags = proton.available(refresh=True)
            GLib.idle_add(self._reload_protons)
            self.say(f"Found {len(tags)} GE-Proton release(s)." if tags
                     else "Could not reach GitHub — showing what's on disk.")

        def _cleanup_protons(self):
            """Report what could be reclaimed; deletion stays explicit."""
            spare = proton.prunable(cfg)
            if not spare:
                self.say("No unused Proton builds to remove.")
                return
            total = sum(b.size() for b in spare) / 1024**3
            names = ", ".join(b.name for b in spare)
            self.say(f"Removable: {names} ({total:.1f} GiB). "
                     f"Remove with: d4l proton remove <name>")

        # -- chrome ----------------------------------------------------
        def _menu(self):
            menu = Gio.Menu()
            menu.append("Open Battle.net", "win.battlenet")
            menu.append("Install / repair game", "win.installgame")
            menu.append("Refresh Proton list", "win.refreshproton")
            menu.append("Unused Proton builds…", "win.cleanproton")
            menu.append("Stop everything", "win.stop")
            menu.append("Run diagnostics", "win.doctor")

            for name, fn in (
                ("battlenet", lambda: battlenet.start_client(cfg)),
                ("installgame", lambda: battlenet.install_game(cfg)),
                ("refreshproton", self._refresh_protons),
                ("cleanproton", self._cleanup_protons),
                ("stop", lambda: procs.terminate(procs.LEFTOVERS + (procs.GAME,),
                                                prefix=cfg.prefix)),
                ("doctor", self._doctor),
            ):
                action = Gio.SimpleAction.new(name, None)
                action.connect("activate", lambda a, p, fn=fn: self.run_bg(fn))
                self.add_action(action)

            return Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)

        def _doctor(self):
            doctor.run(cfg)
            self.say("Diagnostics written to the terminal and log.")

        # -- state -----------------------------------------------------
        def refresh(self):
            if self.busy:
                return True
            st = game.status(cfg)
            if st["game_running"]:
                label, sensitive = "Running", False
            elif not st["battlenet_installed"]:
                label, sensitive = "Set up", True
            elif not st["game_installed"]:
                label, sensitive = "Install game", True
            else:
                label, sensitive = "Play", True
            self.play.set_label(label)
            self.play.set_sensitive(sensitive)
            if not st["umu"] and not self.status.get_label():
                self.say("umu-launcher is missing — sudo pacman -S umu-launcher")
            return True

        def say(self, text):
            GLib.idle_add(self.status.set_label, text)

        def run_bg(self, fn):
            if self.busy:
                return
            self.busy = True
            self.play.set_sensitive(False)
            self.spinner.start()
            log.sink = self.say

            def worker():
                try:
                    fn()
                except runtime.RuntimeError_ as exc:
                    self.say(str(exc).splitlines()[0])
                except Exception as exc:  # never take the window down
                    self.say(f"Unexpected error: {exc}")
                finally:
                    GLib.idle_add(self.done)

            threading.Thread(target=worker, daemon=True).start()

        def done(self):
            self.busy = False
            self.spinner.stop()
            log.sink = None
            self.refresh()
            return False

        # -- actions ---------------------------------------------------
        def on_play(self, _button):
            st = game.status(cfg)
            if not st["battlenet_installed"]:
                self.run_bg(lambda: battlenet.install(cfg))
            elif not st["game_installed"]:
                self.run_bg(lambda: battlenet.install_game(cfg))
            else:
                self.run_bg(lambda: game.play(cfg))

    def on_activate(app):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        Window(app).present()

    app = Adw.Application(application_id="io.github.d4launcher.D4Launcher")
    app.connect("activate", on_activate)
    return app.run([])
