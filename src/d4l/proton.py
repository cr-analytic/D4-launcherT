"""Discovering, selecting and removing Proton builds.

umu resolves PROTONPATH either as an absolute path, as one of a few magic
keywords ("GE-Proton" = latest GE build, auto-downloaded), or as a bare
version name looked up in its compatibility-tool directories. We lean on that:
selecting a version just records the name, and umu downloads it on the next
launch using its own checksum-verified path. No download code here.
"""

from __future__ import annotations

import json
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import log
from .config import STATE_DIR, Config, _xdg

GE_RELEASES = "https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases"
RELEASE_CACHE = STATE_DIR / "ge-releases.json"
CACHE_TTL = 6 * 3600

# Magic values umu understands directly. "GE-Proton" tracks the newest build.
KEYWORDS = {
    "GE-Proton": "Latest GE-Proton, updated automatically",
    "UMU-Proton": "Latest UMU-Proton (Valve Proton + umu patches)",
    "GE-Latest": "Latest GE-Proton, delta-updated in place",
    "UMU-Latest": "Latest UMU-Proton, delta-updated in place",
}


class Build:
    """A Proton build on disk.

    Neither directory umu searches belongs to us alone. Steam's
    compatibilitytools.d is obviously shared; umu's own store is shared too,
    because umu is a general-purpose launcher that Heroic, Lutris and bare
    umu-run all use. So a build is never safe to delete on the grounds that
    "d4l isn't using it" — something else may be.
    """

    def __init__(self, name: str, path: Path, store: str):
        self.name = name
        self.path = path
        # "steam" or "umu" — which compatibility-tool store it lives in.
        self.store = store

    @property
    def shared(self) -> bool:
        """Steam's store: refused outright, since Steam games may need it."""
        return self.store == "steam"

    def size(self) -> int:
        try:
            return sum(f.stat().st_size for f in self.path.rglob("*") if f.is_file())
        except OSError:
            return 0

    def __repr__(self) -> str:
        return f"<Build {self.name} shared={self.shared}>"


def compat_dirs() -> list[tuple[Path, str]]:
    """(directory, store) pairs that umu searches, in resolution order."""
    data = _xdg("XDG_DATA_HOME", ".local/share")
    return [
        (data / "umu" / "compatibilitytools", "umu"),
        (data / "Steam" / "compatibilitytools.d", "steam"),
        (Path.home() / ".steam" / "steam" / "compatibilitytools.d", "steam"),
        (Path.home() / ".steam" / "root" / "compatibilitytools.d", "steam"),
    ]


def _is_proton(path: Path) -> bool:
    return path.is_dir() and ((path / "proton").exists() or (path / "version").exists())


def installed() -> list[Build]:
    """Proton builds present on disk, newest-looking first."""
    found: dict[str, Build] = {}
    for directory, store in compat_dirs():
        if not directory.is_dir():
            continue
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            # First directory wins, so umu's own copy shadows Steam's.
            if _is_proton(entry) and entry.name not in found:
                found[entry.name] = Build(entry.name, entry, store)
    return sorted(found.values(), key=lambda b: _sortkey(b.name), reverse=True)


def _sortkey(name: str):
    """Order GE-Proton11-3 after GE-Proton10-26 rather than alphabetically."""
    digits, part = [], ""
    for ch in name:
        if ch.isdigit():
            part += ch
        elif part:
            digits.append(int(part))
            part = ""
    if part:
        digits.append(int(part))
    return (digits or [0])


def _cached_tags(limit: int) -> list[str]:
    try:
        return json.loads(RELEASE_CACHE.read_text()).get("tags", [])[:limit]
    except (json.JSONDecodeError, OSError):
        return []


def available(refresh: bool = False, limit: int = 15,
              network: bool = True) -> list[str]:
    """Recent GE-Proton release tags, cached so we don't hammer the API.

    network=False never blocks: it returns whatever is cached, even if stale.
    The GUI uses that on the UI thread and refreshes from a worker.
    """
    if not refresh and RELEASE_CACHE.exists():
        try:
            blob = json.loads(RELEASE_CACHE.read_text())
            if time.time() - blob.get("fetched", 0) < CACHE_TTL:
                return blob.get("tags", [])[:limit]
        except (json.JSONDecodeError, OSError):
            pass

    if not network:
        return _cached_tags(limit)

    try:
        req = urllib.request.Request(
            f"{GE_RELEASES}?per_page={limit}",
            headers={"User-Agent": "d4-launcher", "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            tags = [r["tag_name"] for r in json.load(resp) if not r.get("prerelease")]
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        log.warn(f"Could not fetch the GE-Proton release list: {exc}")
        # Fall back to a stale cache rather than showing nothing.
        return _cached_tags(limit)

    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        RELEASE_CACHE.write_text(json.dumps({"fetched": time.time(), "tags": tags}))
    except OSError:
        pass
    return tags[:limit]


def choices(refresh: bool = False, network: bool = True) -> list[tuple[str, str]]:
    """(value, human label) pairs for the picker."""
    on_disk = {b.name: b for b in installed()}
    out = [(k, f"{k} — {desc}") for k, desc in KEYWORDS.items()]
    out += [(b.name, f"{b.name} — installed" + (" (Steam)" if b.shared else ""))
            for b in on_disk.values()]
    out += [(tag, f"{tag} — will download on next launch")
            for tag in available(refresh=refresh, network=network)
            if tag not in on_disk]
    return out


# --------------------------------------------------------------------------
# Switching
# --------------------------------------------------------------------------

def clear_caches(cfg: Config) -> int:
    """Drop the DXVK/VKD3D shader caches so they rebuild against the new Proton.

    Cheap insurance: a stale cache after a Proton swap costs stutter at worst
    and confusing behaviour at best, and rebuilding only costs a few minutes
    of shader compilation during the first play session.
    """
    cache = cfg.game_dir / "cache"
    removed = 0
    if cache.is_dir():
        for item in cache.iterdir():
            try:
                if item.is_file():
                    item.unlink()
                    removed += 1
            except OSError:
                pass
    cache.mkdir(parents=True, exist_ok=True)
    return removed


def remove(name: str, cfg: Config | None = None, confirm=None) -> bool:
    """Delete an installed Proton build. Refuses shared and in-use builds.

    `confirm` is called with the Build before deletion; returning False aborts.
    Builds in umu's store can be in use by other umu-launched games, and
    nothing on disk tells us which — so the caller gets to ask a human.
    """
    if cfg is not None and name == cfg["proton"]:
        log.error(f"{name} is the version currently selected — switch away first.")
        return False
    if name in KEYWORDS:
        log.error(f"{name} is an alias, not an installed build.")
        return False

    for build in installed():
        if build.name != name:
            continue
        if build.shared:
            log.error(
                f"{name} lives in Steam's compatibilitytools.d and may be in use "
                f"by other games — not touching it.\n  {build.path}"
            )
            return False
        if confirm is not None and not confirm(build):
            log.info("Left it alone.")
            return False
        try:
            shutil.rmtree(build.path)
        except OSError as exc:
            log.error(f"Could not remove {name}: {exc}")
            return False
        log.info(f"Removed {name}.")
        return True

    log.error(f"{name} is not installed.")
    return False


def prunable(cfg: Config) -> list[Build]:
    """Builds deletion is *permitted* for — not builds proven to be unused.

    These live in umu's store, which other umu-launched games share, so this
    is a candidate list for a human to look at, never a list to delete
    automatically.
    """
    return [b for b in installed() if not b.shared and b.name != cfg["proton"]]


def use(cfg: Config, name: str, prune: bool | None = None) -> bool:
    """Select a Proton version, clear caches, and optionally prune the old one."""
    previous = cfg["proton"]
    if name == previous:
        log.info(f"Already using {name}.")
        return True

    cfg["proton"] = name
    cfg.save()
    log.info(f"Proton set to {name}.")

    cleared = clear_caches(cfg)
    if cleared:
        log.info(f"Cleared {cleared} cached shader file(s); they rebuild on next launch.")

    if prune is None:
        prune = bool(cfg["prune_old_proton"])
    if prune and previous not in KEYWORDS:
        old = next((b for b in installed() if b.name == previous), None)
        if old is None:
            pass  # nothing on disk to reclaim
        elif old.shared:
            # Don't silently ignore --prune; say why we're keeping it.
            log.warn(f"Keeping {previous}: it lives in Steam's compatibilitytools.d "
                     "and other games may be using it.")
        else:
            log.warn(f"Pruning {previous} from umu's shared tool directory — "
                     "other umu-launched games could have been using it.")
            remove(previous, cfg)

    if not any(b.name == name for b in installed()) and name not in KEYWORDS:
        log.info(f"{name} isn't downloaded yet — umu will fetch it on the next launch.")
    return True
