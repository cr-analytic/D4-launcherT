"""Command line interface for d4l."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from . import battlenet, config as cfgmod, doctor, game, log, procs, proton, runtime

DESC = "Launch Diablo IV on Linux without going through Lutris and Battle.net by hand."


def cmd_setup(cfg, args) -> int:
    """First-run: create the prefix, install Battle.net, log in once."""
    log.info(f"Game directory: {cfg.game_dir}")
    cfg.game_dir.mkdir(parents=True, exist_ok=True)

    battlenet.install(cfg, verbose=args.verbose)
    battlenet.tune_config(cfg)

    if cfg.find_game_exe():
        log.info("Diablo IV is already installed. You're done — run `d4l play`.")
        return 0

    print()
    log.info("Next: install Diablo IV through Battle.net (`d4l install-game`),")
    log.info("then launch it any time with `d4l play` or the desktop shortcut.")
    return 0


def cmd_play(cfg, args) -> int:
    return game.play(cfg, verbose=args.verbose, wait=not args.no_wait)


def cmd_install_game(cfg, args) -> int:
    battlenet.install_game(cfg, verbose=args.verbose)
    return 0


def cmd_battlenet(cfg, args) -> int:
    battlenet.tune_config(cfg)
    return 0 if battlenet.start_client(cfg, verbose=args.verbose) else 1


def cmd_stop(cfg, args) -> int:
    names = procs.LEFTOVERS + ((procs.GAME,) if args.all else ())
    n = procs.terminate(names)
    log.info(f"Stopped {n} process(es)." if n else "Nothing was running.")
    return 0


def cmd_status(cfg, args) -> int:
    st = game.status(cfg)
    if args.json:
        print(json.dumps(st, indent=2))
        return 0
    for key, value in st.items():
        print(f"  {key:20} {value}")
    return 0


def cmd_doctor(cfg, args) -> int:
    return doctor.run(cfg)


def cmd_config(cfg, args) -> int:
    if not args.set:
        print(json.dumps(dict(cfg), indent=2))
        print(f"\n({cfgmod.CONFIG_FILE})", file=sys.stderr)
        return 0

    for pair in args.set:
        if "=" not in pair:
            log.error(f"Expected key=value, got: {pair}")
            return 2
        key, _, raw = pair.partition("=")
        key = key.strip()
        if key not in cfgmod.DEFAULTS:
            log.error(f"Unknown setting: {key}")
            return 2
        current = cfgmod.DEFAULTS[key]
        try:
            if isinstance(current, bool):
                value = raw.strip().lower() in ("1", "true", "yes", "on")
            elif isinstance(current, (dict, list)):
                value = json.loads(raw)
            else:
                value = raw
        except json.JSONDecodeError as exc:
            log.error(f"Could not parse value for {key}: {exc}")
            return 2
        cfg[key] = value
        print(f"  {key} = {json.dumps(value)}")
    cfg.save()
    return 0


def _human(size: int) -> str:
    for unit in ("B", "KiB", "MiB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} GiB"


def cmd_proton(cfg, args) -> int:
    if args.proton_action == "use":
        prune = True if args.prune else (False if args.keep else None)
        return 0 if proton.use(cfg, args.name, prune=prune) else 1

    if args.proton_action == "remove":
        return 0 if proton.remove(args.name, cfg) else 1

    # list (default)
    active = cfg["proton"]
    on_disk = {b.name: b for b in proton.installed()}

    print("\n  Selected:", active, "\n")
    print("  Installed:")
    if on_disk:
        for build in on_disk.values():
            mark = "*" if build.name == active else " "
            where = "Steam (shared)" if build.shared else "umu"
            print(f"   {mark} {build.name:<22} {_human(build.size()):>9}  {where}")
    else:
        print("     (none yet — umu downloads one on the first launch)")

    print("\n  Aliases:")
    for key, desc in proton.KEYWORDS.items():
        mark = "*" if key == active else " "
        print(f"   {mark} {key:<22} {desc}")

    extra = [t for t in proton.available(refresh=args.refresh) if t not in on_disk]
    if extra:
        print("\n  Available to download:")
        print("     " + ", ".join(extra[:10]))
    print()
    return 0


def cmd_logs(cfg, args) -> int:
    if not cfgmod.LOG_FILE.exists():
        log.warn("No log file yet.")
        return 0
    if args.follow:
        try:
            subprocess.run(["tail", "-f", str(cfgmod.LOG_FILE)])
        except KeyboardInterrupt:
            pass
        return 0
    print(cfgmod.LOG_FILE.read_text(), end="")
    return 0


def cmd_gui(cfg, args) -> int:
    from .ui import gtk_app
    return gtk_app.main(cfg)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="d4l", description=DESC)
    p.add_argument("-v", "--verbose", action="store_true",
                   help="verbose umu/Proton logging")
    sub = p.add_subparsers(dest="command")

    sub.add_parser("setup", help="first-run install of Battle.net into the prefix")

    play = sub.add_parser("play", help="launch Diablo IV (the one-click path)")
    play.add_argument("--no-wait", action="store_true",
                      help="exit once the game starts instead of cleaning up after it")

    sub.add_parser("install-game", help="open Battle.net's Diablo IV install flow")
    sub.add_parser("battlenet", help="just open the Battle.net client")

    stop = sub.add_parser("stop", help="close Battle.net and its helpers")
    stop.add_argument("--all", action="store_true", help="also close the game")

    st = sub.add_parser("status", help="what is installed and running")
    st.add_argument("--json", action="store_true")

    sub.add_parser("doctor", help="check this machine can run the game")

    cf = sub.add_parser("config", help="show or change settings")
    cf.add_argument("--set", action="append", metavar="KEY=VALUE",
                    help="change a setting (repeatable)")

    pr = sub.add_parser("proton", help="list, switch or remove Proton versions")
    pra = pr.add_subparsers(dest="proton_action")
    prl = pra.add_parser("list", help="show installed and available versions")
    prl.add_argument("--refresh", action="store_true",
                     help="re-fetch the GE-Proton release list")
    pru = pra.add_parser("use", help="switch version (clears shader caches)")
    pru.add_argument("name", help="e.g. GE-Proton11-3, or the alias GE-Proton")
    pru.add_argument("--prune", action="store_true",
                     help="delete the version being switched away from")
    pru.add_argument("--keep", action="store_true",
                     help="keep it, overriding prune_old_proton")
    prr = pra.add_parser("remove", help="delete an installed version")
    prr.add_argument("name")

    lg = sub.add_parser("logs", help="show the d4l log")
    lg.add_argument("-f", "--follow", action="store_true")

    sub.add_parser("gui", help="open the graphical launcher")
    return p


HANDLERS = {
    "setup": cmd_setup, "play": cmd_play, "install-game": cmd_install_game,
    "battlenet": cmd_battlenet, "stop": cmd_stop, "status": cmd_status,
    "doctor": cmd_doctor, "config": cmd_config, "logs": cmd_logs, "gui": cmd_gui,
    "proton": cmd_proton,
}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    cfg = cfgmod.load()

    # Bare `d4l` should do the obvious thing rather than print usage.
    command = args.command or ("play" if cfg.bnet_exe.exists() else "setup")
    handler = HANDLERS[command]
    for attr, default in (("no_wait", False), ("all", False), ("json", False),
                          ("set", None), ("follow", False), ("refresh", False),
                          ("proton_action", "list"), ("name", None),
                          ("prune", False), ("keep", False)):
        if not hasattr(args, attr):
            setattr(args, attr, default)

    try:
        return handler(cfg, args)
    except runtime.RuntimeError_ as exc:
        log.error(str(exc))
        return 1
    except KeyboardInterrupt:
        return 130
