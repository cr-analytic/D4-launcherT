# d4-launcher

A minimal one-click Diablo IV launcher for Linux. Replaces the
Lutris → Battle.net → click Play → click Play again dance with a single icon
in your application menu.

Log in to Battle.net once, during setup. After that Diablo IV starts like any
locally installed game — the Battle.net client is an implementation detail you
never touch again.

Built for CachyOS; works on any Arch-based system, and on other distros if you
install `umu-launcher` yourself.

---

## Install

```bash
git clone https://github.com/cr-analytic/d4-launcherT.git
cd d4-launcherT
./install.sh
```

The installer checks your dependencies (offering to `pacman -S` anything
missing), installs the launcher into `~/.local`, adds the desktop entries, and
then offers to run first-time setup.

Setup creates the Wine prefix, downloads the official Battle.net installer from
Blizzard, and opens Battle.net so you can log in. **Tick "Remember my
account"** — that is the one and only time you need to do this. Then install
Diablo IV through Battle.net as usual.

From then on:

```bash
d4l play          # or just click "Diablo IV" in your app menu
```

Prefer a system-wide package? `makepkg -si` uses the included `PKGBUILD`.

---

## Usage

| Command | What it does |
|---|---|
| `d4l` | Plays the game, or runs setup if you haven't yet |
| `d4l play` | Launch Diablo IV |
| `d4l gui` | Small graphical launcher window |
| `d4l setup` | First-run: prefix + Battle.net install |
| `d4l install-game` | Open Battle.net's Diablo IV install flow |
| `d4l battlenet` | Just open the Battle.net client |
| `d4l proton` | List, switch or remove Proton versions |
| `d4l stop` | Close Battle.net and its leftovers *in this prefix* (`--all` also closes the game) |
| `d4l status` | What's installed and running (`--json` for scripts) |
| `d4l move <dir>` | Move the install (game, prefix, login) to another disk |
| `d4l doctor` | Check drivers, Vulkan, disk space, install state |
| `d4l ps` | Wine processes and which prefix they belong to |
| `d4l config` | Show settings; `--set key=value` to change them |
| `d4l logs` | Show the log (`-f` to follow) |

Two entries land in your application menu: **Diablo IV**, which launches the
game directly, and **D4 Launcher** for the GUI.

### Adding it to Steam

If you want it in your Steam library, add a non-Steam game pointing at
`~/.local/bin/d4l` with `play` as the launch option. Leave Steam's
compatibility layer **off** — d4l runs its own Proton via umu, and letting
Steam wrap it too would nest two Proton environments.

---

## Proton versions

A bad Proton version is the usual reason Battle.net or D4 breaks, so switching
is a first-class control rather than a settings page — there's a dropdown in
the launcher window, and:

```bash
d4l proton list                     # installed, aliases, and downloadable
d4l proton use GE-Proton11-3        # switch (clears shader caches)
d4l proton use GE-Proton            # alias: always track the newest build
d4l proton remove GE-Proton11-1     # reclaim the disk space
```

Picking a version you don't have is fine — umu downloads it on the next
launch, using its own checksum-verified path. Switching always clears the DXVK
and VKD3D shader caches, so they rebuild against the new Proton; expect the
first session afterwards to stutter a little while they warm up.

### Switching only ever affects Diablo IV

Choosing a version writes `proton` in d4l's own config, which becomes
`PROTONPATH` only when d4l launches the game. Steam, Lutris and Heroic read
their own settings and are completely unaffected; a download adds a new
directory and changes nothing that already exists. **There is no way for
switching versions here to alter what another game runs.**

Deleting is the only operation that could reach beyond D4, which is why it's
hedged as described below.

### Why the old version isn't deleted automatically

You can have that — `d4l proton use <name> --prune`, or
`d4l config --set prune_old_proton=true` to make it the default. It's off out
of the box for two reasons:

- **Rolling back is the whole point.** You switch versions *because* a build
  regressed, which means the version you want next is very often the one you
  just left. Deleting it turns a two-second switch into another download.
  Keeping two or three builds costs ~1–2 GB against a ~90 GB game.
- **Neither tool directory belongs to d4l alone.** umu looks in its own
  `~/.local/share/umu/compatibilitytools` *and* in
  `~/.local/share/Steam/compatibilitytools.d`. The Steam one obviously
  belongs to Steam — d4l refuses to delete from it outright. But umu's own
  store is shared too, because Heroic, Lutris and bare `umu-run` all use umu,
  and nothing on disk records which build another game depends on.

So `d4l proton remove` asks before deleting (`--yes` to skip, required when
not on a terminal), and `--prune` warns as it goes. Removal also refuses the
version currently selected. **Unused Proton builds…** in the launcher menu
reports what *may* be removable and its size, and deliberately doesn't delete
anything itself.

Switching Proton while the game or Battle.net is running is blocked — the
prefix is in use, and changing it underneath a running process is asking for
trouble. Close things first.

> Downgrading across a major version (11 → 10) reuses a prefix that the newer
> Proton may have upgraded. It usually works; if it doesn't, the clean fix is
> to move `<game_dir>/prefix` aside and re-run `d4l setup`. That means logging
> in again, but not re-downloading the game if you point the install at the
> same folder.

---

## Configuration

`d4l config` prints everything; `~/.config/d4-launcher/config.json` holds it.

```bash
d4l config --set game_dir=/mnt/games/diablo4   # put the ~90 GB somewhere else
d4l config --set proton=GE-Proton               # or an absolute Proton path
d4l config --set gamemode=true                  # wrap in gamemoderun
d4l config --set mangohud=true                  # performance overlay
d4l config --set raytracing=true                # VKD3D_CONFIG=dxr11
d4l config --set nvidia_dlss=false              # off by default on non-NVIDIA
d4l config --set close_battlenet_after_exit=true    # close the client when you quit
d4l config --set battlenet_on_game_launch=minimize  # keep|minimize|close|"" (leave alone)
d4l config --set prune_old_proton=true          # delete the old Proton on switch
d4l config --set 'env={"WINEDLLOVERRIDES":"foo=n,b"}'   # escape hatch
```

To put the install on another disk, use `d4l move` rather than editing
`game_dir` by hand — the setting only says where to *look*, so changing it on
its own just points the launcher at an empty directory (and a subsequent
`d4l setup` will cheerfully build a second install there).

```bash
d4l move /mnt/games/diablo4
```

This carries the game, the Wine prefix and your Battle.net login across in one
piece — no re-download, no logging in again. On the same filesystem it's an
instant rename. Across disks it copies, verifies Battle.net is present at the
new path, and **leaves the original alone** so a failed 90 GB move can't cost
you the install; it prints the `rm -rf` to run once `d4l play` works from the
new location.

It refuses to run if the game or Battle.net is open, if the destination exists
and isn't empty, or if the target drive is too small, and it puts `game_dir`
back if the moved copy doesn't check out.

Useful defaults it sets for you:

- Shader caches (`DXVK_STATE_CACHE_PATH`, `VKD3D_SHADER_CACHE_PATH`) persist in
  `<game_dir>/cache`, so you only pay the stutter tax once.
- On NVIDIA, NVAPI and the NGX updater are enabled so DLSS works.
- Battle.net's hardware acceleration is switched off — Blizzard's own
  troubleshooting step, and its Chromium-based UI is far more stable that way
  under Wine.
- The Battle.net client is left running and left to you: d4l doesn't close it
  when the game exits, and never restarts one you closed. `d4l stop` closes it
  when you want that, and `close_battlenet_after_exit=true` makes it automatic.

Setting `battlenet_on_game_launch=close` is possible but not advised: the
client exits *during* the launch, so there's nothing left for a follow-up
command to reach, and a retry ends up starting a fresh Battle.net rather than
talking to the running one.

---

## How it works

```
d4l play
  └─ umu-run ──> Proton (GE-Proton) ──> WINEPREFIX=<game_dir>/prefix
        ├─ start Battle.net.exe if it isn't already running
        ├─ wait until its UI helper processes exist (i.e. it's actually ready)
        ├─ Battle.net.exe --exec="launch Fen"      ← "Fen" = Diablo IV (Fenris)
        ├─ retry if the game process doesn't appear
        └─ when Diablo IV exits, close Battle.net and its helpers
```

Three details are what make this less annoying than doing it by hand:

**The launch command gets swallowed.** `--exec="launch Fen"` only works if the
Battle.net client is already up and initialised. Fire it too early — which is
exactly what happens when a script starts the client and immediately asks it to
launch — and nothing happens. The usual advice is "run it twice, with a sleep
in between". d4l instead waits for Battle.net's Chromium helper processes to
appear (a real readiness signal, not a guessed sleep), then re-sends the launch
command if the game process hasn't shown up, with an escalating timeout. Cold
start lands around 15–20 seconds; if Battle.net is already running, it's
immediate.

**Process detection is done on `/proc/<pid>/comm`, not `pgrep -f`.** Wine sets
`comm` to the Windows executable name. Matching command lines instead would
match `umu-run …/Battle.net.exe` — the launcher's own invocation — and the
tool would think the client was running when it wasn't.

**Nothing is left behind — and nothing else is touched.** Battle.net's agent
and helper processes outlive the game and keep the prefix busy, so `d4l play`
reaps them once you quit. Every process it signals must belong to *this*
prefix, checked by reading `WINEPREFIX`/`STEAM_COMPAT_DATA_PATH` out of
`/proc/<pid>/environ`. If you have Battle.net open for WoW in a separate
Lutris prefix, quitting D4 leaves it running. Anything d4l cannot positively
attribute to its own prefix is left alone; `d4l stop --any-prefix` overrides
that if something is genuinely stuck.

Your login lives in the Wine prefix, the same way it would on Windows, so it
survives reboots and updates. Nothing about your account is stored by this
tool — it has no idea what your credentials are.

---

## Troubleshooting

Start with `d4l doctor`. Then `d4l logs`.

**`umu-run not found`** — `sudo pacman -S umu-launcher` (enable `multilib` in
`/etc/pacman.conf` if pacman can't find it).

**The GUI won't start** — it needs `python-gobject libadwaita gtk4`. The CLI
works regardless; `d4l play` never needs them.

**Battle.net won't download during setup** — grab the installer from
<https://battle.net/download> manually and save it as
`<game_dir>/Battle.net-Setup.exe`, then re-run `d4l setup`.

**The game doesn't launch, and Battle.net is sitting there** — usually it wants
to patch. Let the update finish in the Battle.net window and run `d4l play`
again.

**Battle.net's window is blank or garbled** — hardware acceleration is the
usual culprit; d4l disables it, but if you re-enabled it, turn it back off with
`d4l config --set disable_bnet_hardware_accel=true` and restart the client.

**A launch went wrong and things are stuck** — `d4l stop --all`.

**Try a different Proton** — the dropdown in the launcher, or
`d4l proton use GE-Proton11-3`. Battle.net regressions are common and usually
fixed in a later GE-Proton; the `GE-Proton` alias (the default) always tracks
the newest. See [Proton versions](#proton-versions).

Verbose Proton/umu logging: `d4l -v play`.

---

## Uninstall

```bash
./uninstall.sh
```

Removes the launcher and leaves your game and prefix alone; it tells you the
directory to delete if you want the disk space back.

---

## Notes

Not affiliated with Blizzard Entertainment. No Blizzard code or assets are
included — setup downloads the official Battle.net installer from Blizzard.
This is a convenience wrapper around software you already own, using the same
client and the same login you would use on Windows.

MIT licensed.
