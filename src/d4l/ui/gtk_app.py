"""A deliberately small GTK4/libadwaita launcher window.

One button that does the right thing depending on what is installed, a status
line, and nothing else. If PyGObject or libadwaita aren't available we say so
and point at the CLI rather than failing with a traceback.
"""

from __future__ import annotations

import sys
import threading

from .. import battlenet, config as cfgmod, doctor, game, log, procs, runtime

CSS = b"""
.d4-title    { font-size: 30px; font-weight: 800; letter-spacing: 5px; }
.d4-subtitle { font-size: 12px; letter-spacing: 3px; opacity: 0.55; }
.d4-play     { font-size: 17px; font-weight: 700; padding: 14px 0; }
.d4-status   { font-size: 12px; opacity: 0.7; }
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

            root.append(body)
            self.set_content(root)

            self.refresh()
            # Keep the button honest if the game is started or closed elsewhere.
            GLib.timeout_add_seconds(3, self.refresh)

        # -- chrome ----------------------------------------------------
        def _menu(self):
            menu = Gio.Menu()
            menu.append("Open Battle.net", "win.battlenet")
            menu.append("Install / repair game", "win.installgame")
            menu.append("Stop everything", "win.stop")
            menu.append("Run diagnostics", "win.doctor")

            for name, fn in (
                ("battlenet", lambda: battlenet.start_client(cfg)),
                ("installgame", lambda: battlenet.install_game(cfg)),
                ("stop", lambda: procs.terminate(procs.LEFTOVERS + (procs.GAME,))),
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
