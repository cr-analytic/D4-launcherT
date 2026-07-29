"""A deliberately small GTK4/libadwaita launcher window.

One button that does the right thing depending on what is installed, a status
line, and nothing else. If PyGObject or libadwaita aren't available we say so
and point at the CLI rather than failing with a traceback.
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
from pathlib import Path

from .. import (battlenet, config as cfgmod, doctor, game, log, move, procs,
                proton, runtime)

# Diablo IV is roughly 90 GB installed; leave headroom for patches and the
# shader cache before calling a drive big enough.
NEEDED_GIB = 120

CSS = b"""
.d4-title    { font-size: 30px; font-weight: 800; letter-spacing: 5px; }
.d4-subtitle { font-size: 12px; letter-spacing: 3px; opacity: 0.55; }
.d4-play     { font-size: 17px; font-weight: 700; padding: 14px 0; }
.d4-status   { font-size: 12px; opacity: 0.7; }
.d4-proton   { font-size: 11px; opacity: 0.6; letter-spacing: 1px; }
.d4-check    { font-size: 12px; opacity: 0.75; }
"""

# Seconds between Battle.net coming up and the window closing itself. Shown
# in the checkbox label, so keep the two in step.
AUTOCLOSE_DELAY = 3


def _missing(exc: Exception) -> int:
    print(
        f"bnl: the graphical launcher needs GTK4 and libadwaita ({exc}).\n"
        "     Install them with:  sudo pacman -S python-gobject libadwaita gtk4\n"
        "     Or just use the command line:  bnl play",
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
            super().__init__(application=app, title=cfgmod.APP_NAME)
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
            body.append(Gtk.Label(label="BATTLE.NET", css_classes=["d4-title"]))
            body.append(Gtk.Label(label=cfgmod.distro(),
                                  css_classes=["d4-subtitle"]))

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

            # Shown only while a move is running; replaced by a plain
            # completion message afterwards.
            self.progress = Gtk.ProgressBar(show_text=True, visible=False,
                                            margin_top=10)
            body.append(self.progress)

            self.location_box = self._location_row()
            body.append(self.location_box)

            self.autoclose = Gtk.CheckButton(
                label=f"Close this window {AUTOCLOSE_DELAY} seconds "
                      "after Battle.net starts",
                active=bool(cfg["close_gui_after_launch"]),
                halign=Gtk.Align.CENTER, margin_top=10,
                css_classes=["d4-check"],
            )
            self.autoclose.connect("toggled", self.on_autoclose)
            body.append(self.autoclose)

            body.append(self._proton_picker())

            root.append(body)
            self.set_content(root)

            self.refresh()
            # Keep the button honest if the game is started or closed elsewhere.
            GLib.timeout_add_seconds(3, self.refresh)

        # -- install location ------------------------------------------
        def _location_row(self):
            """Where the ~90 GB goes. Shown only before anything is installed.

            Choosing the drive here is the whole point: afterwards the game,
            the prefix and the login all live under this path, and changing
            it means physically moving them (`bnl move`).
            """
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5,
                          margin_top=18)
            box.append(Gtk.Label(label="INSTALL LOCATION",
                                 css_classes=["d4-proton"],
                                 halign=Gtk.Align.CENTER))

            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            self.location = Gtk.Entry(hexpand=True, text=str(cfg.game_dir))
            # Only ever read in refresh(), never written — otherwise the
            # three-second poll would fight whatever is being typed.
            self.location.connect("changed", lambda *_: self._update_space())
            row.append(self.location)

            browse = Gtk.Button(icon_name="folder-open-symbolic",
                                tooltip_text="Choose a folder")
            browse.connect("clicked", self.on_browse)
            row.append(browse)
            box.append(row)

            self.space = Gtk.Label(css_classes=["d4-status"], wrap=True)
            box.append(self.space)
            self._update_space()
            return box

        def _update_space(self):
            text = self.location.get_text().strip() or "~"
            path = Path(os.path.expanduser(text))
            probe = path
            while not probe.exists() and probe != probe.parent:
                probe = probe.parent
            try:
                free = shutil.disk_usage(probe).free / 1024**3
            except OSError:
                self.space.set_text("Can't read that path.")
                return
            if free >= NEEDED_GIB:
                self.space.set_text(f"{free:.0f} GiB free — room for Diablo IV")
            else:
                self.space.set_text(
                    f"{free:.0f} GiB free — Diablo IV wants about {NEEDED_GIB} GiB")

        def on_browse(self, _button):
            try:
                dialog = Gtk.FileDialog(title="Where should the game go?")
            except (AttributeError, TypeError):
                self.say("Type the path — this GTK is too old for the picker.")
                return
            start = Path(os.path.expanduser(self.location.get_text().strip() or "~"))
            while not start.is_dir() and start != start.parent:
                start = start.parent
            dialog.set_initial_folder(Gio.File.new_for_path(str(start)))

            def chosen(dlg, result):
                try:
                    folder = dlg.select_folder_finish(result)
                except GLib.Error:
                    return  # cancelled
                if folder and folder.get_path():
                    # A bare drive root is rarely what's wanted; keep the
                    # install in its own directory.
                    picked = Path(folder.get_path())
                    if picked.name.lower() not in ("diablo4", "diablo-iv"):
                        picked = picked / "diablo4"
                    self.location.set_text(str(picked))

            dialog.select_folder(self, None, chosen)

        def _apply_location(self) -> bool:
            """Persist the chosen path before setup runs. False if unusable."""
            text = self.location.get_text().strip()
            if not text:
                return True
            path = Path(os.path.expanduser(text)).absolute()
            # Actually create it and write a file, rather than asking
            # os.access: permission bits say nothing about read-only mounts
            # or filesystems that refuse directories, and for root they
            # always say yes. Setup would create this directory anyway.
            try:
                path.mkdir(parents=True, exist_ok=True)
                probe = path / ".bnl-write-test"
                probe.touch()
                probe.unlink()
            except OSError as exc:
                self.say(f"Can't use {path}: {exc.strerror or exc}.")
                return False
            cfg["game_dir"] = str(path)
            cfg.save()
            return True

        # -- moving an existing install --------------------------------
        def on_move_install(self):
            """Pick a destination, then move the install there with progress.

            Runs on the UI thread: the file dialog must, and the copy is
            handed to a worker once a folder is chosen.
            """
            if not game.status(cfg)["battlenet_installed"]:
                self.say("Nothing installed to move yet.")
                return
            if self.busy:
                return
            try:
                dialog = Gtk.FileDialog(title="Move the install to…")
            except (AttributeError, TypeError):
                self.say("This GTK is too old for the picker — use: bnl move <dir>")
                return

            start = cfg.game_dir.parent if cfg.game_dir.parent.is_dir() else Path.home()
            dialog.set_initial_folder(Gio.File.new_for_path(str(start)))

            def chosen(dlg, result):
                try:
                    folder = dlg.select_folder_finish(result)
                except GLib.Error:
                    return  # cancelled
                if not folder or not folder.get_path():
                    return
                target = Path(folder.get_path())
                if target.name.lower() not in ("diablo4", "diablo-iv"):
                    target = target / "diablo4"
                self.run_bg(lambda: self._do_move(target))

            dialog.select_folder(self, None, chosen)

        def _set_progress(self, fraction):
            self.progress.set_visible(True)
            self.progress.set_fraction(fraction)
            self.progress.set_text(f"{fraction * 100:.0f}%")
            return False

        def _do_move(self, dest):
            source = cfg.game_dir
            GLib.idle_add(self._set_progress, 0.0)
            try:
                move.relocate(cfg, str(dest),
                              progress=lambda f: GLib.idle_add(self._set_progress, f))
            finally:
                # The bar is transient: on success the completion message
                # takes its place, on failure run_bg reports the error.
                GLib.idle_add(self.progress.set_visible, False)
            self.say(f"Move complete — now at {dest}. The old copy is still at "
                     f"{source}; delete it once you're happy.")

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
                     f"Remove with: bnl proton remove <name>")

        # -- chrome ----------------------------------------------------
        def _menu(self):
            menu = Gio.Menu()
            # Auto-launching the game is available but never automatic: the
            # button brings up Battle.net and stops.
            menu.append("Launch Diablo IV too", "win.playgame")
            menu.append("Install / repair game", "win.installgame")
            menu.append("Move install…", "win.moveinstall")
            menu.append("Refresh Proton list", "win.refreshproton")
            menu.append("Unused Proton builds…", "win.cleanproton")
            menu.append("Stop everything", "win.stop")
            menu.append("Run diagnostics", "win.doctor")

            # `direct` actions run on the UI thread — a file dialog has to.
            # Everything else goes to a worker so the window stays alive.
            for name, fn, direct in (
                ("playgame", lambda: game.play(cfg, wait=False), False),
                ("installgame", lambda: battlenet.install_game(cfg), False),
                ("moveinstall", self.on_move_install, True),
                ("refreshproton", self._refresh_protons, False),
                ("cleanproton", self._cleanup_protons, False),
                ("stop", lambda: procs.terminate(procs.LEFTOVERS + (procs.GAME,),
                                                 prefix=cfg.prefix), False),
                ("doctor", self._doctor, False),
            ):
                action = Gio.SimpleAction.new(name, None)
                if direct:
                    action.connect("activate", lambda a, p, fn=fn: fn())
                else:
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
                label, sensitive = "Diablo IV running", False
            elif st["battlenet_running"]:
                label, sensitive = "Battle.net running", False
            elif not st["battlenet_installed"]:
                label, sensitive = "Set up", True
            else:
                label, sensitive = "Launch Battle.net", True
            self.play.set_label(label)
            self.play.set_sensitive(sensitive)
            # The path is only editable while there is nothing installed at
            # it; afterwards moving is a filesystem operation, not a setting.
            self.location_box.set_visible(not st["battlenet_installed"])
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
            """Bring up Battle.net and stop there.

            Starting the game is left to the user, in Battle.net, where the
            patch state and the Play button already are. The launcher's job
            is getting the client running under Proton, not second-guessing
            what happens next.
            """
            if not game.status(cfg)["battlenet_installed"]:
                if not self._apply_location():
                    return
                self.run_bg(lambda: battlenet.install(cfg))
            else:
                self.run_bg(lambda: self._open_battlenet())

        def on_autoclose(self, button):
            cfg["close_gui_after_launch"] = button.get_active()
            cfg.save()

        def _open_battlenet(self):
            if not battlenet.start_client(cfg):
                return
            if cfg["close_gui_after_launch"]:
                self.say(f"Battle.net is up — closing in {AUTOCLOSE_DELAY}s.")
                # Nothing here supervises the client, so quitting is safe.
                GLib.timeout_add(AUTOCLOSE_DELAY * 1000,
                                 self.get_application().quit)
            else:
                self.say("Battle.net is up — launch Diablo IV from there. "
                         "You can close this window; it won't stop anything.")

    def on_activate(app):
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        Window(app).present()

    app = Adw.Application(
        application_id="io.github.battlenetlauncher4linux.Launcher")
    app.connect("activate", on_activate)
    return app.run([])
