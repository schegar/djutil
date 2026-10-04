"""OS-specific Rekordbox path discovery (Windows + macOS)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import NamedTuple

from platformdirs import user_data_dir

ENV_DB_PATH = "DJUTIL_RB_DB"


class RekordboxDirs(NamedTuple):
    options_json: Path
    share_dir: Path


def rekordbox_dirs(
    platform: str | None = None,
    home: Path | None = None,
    appdata: str | None = None,
) -> RekordboxDirs:
    """Return the location of ``options.json`` and the ``share`` dir per OS.

    Mirrors unbox's ``getRekordboxPaths``.
    """
    platform = platform if platform is not None else sys.platform
    home = home if home is not None else Path.home()

    if platform == "darwin":
        return RekordboxDirs(
            home
            / "Library"
            / "Application Support"
            / "Pioneer"
            / "rekordboxAgent"
            / "storage"
            / "options.json",
            home / "Library" / "Pioneer" / "rekordbox" / "share",
        )
    if platform.startswith("win"):
        appdata = appdata if appdata is not None else os.environ.get("APPDATA", "")
        if not appdata:
            raise FileNotFoundError("APPDATA environment variable not set on Windows")
        base = Path(appdata) / "Pioneer"
        return RekordboxDirs(
            base / "rekordboxAgent" / "storage" / "options.json",
            base / "rekordbox" / "share",
        )
    config_dir = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    return RekordboxDirs(
        config_dir / "Pioneer" / "rekordboxAgent" / "storage" / "options.json",
        home / ".local" / "share" / "Pioneer" / "rekordbox" / "share",
    )


def parse_options_json(text: str) -> str | None:
    """Extract the master.db path from rekordboxAgent's ``options.json``.

    Two formats exist in the wild (see unbox ``pollRekordbox``):
    - new: ``{"options": [["<key>", "<db path>", ...], ...]}``
    - old: any top-level object containing an ``"options"`` list-of-lists
      (possibly nested one level deeper).

    Returns ``None`` if no usable path is found.
    """
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    options = data.get("options")
    # Some old files wrap the payload one level deeper.
    if isinstance(options, dict):
        options = options.get("options")
    if not isinstance(options, list):
        # Old format: find the first top-level list-of-lists value.
        options = next(
            (
                v
                for v in data.values()
                if isinstance(v, list) and v and isinstance(v[0], list)
            ),
            None,
        )
    if (
        not isinstance(options, list)
        or not options
        or not isinstance(options[0], list)
        or len(options[0]) < 2
    ):
        return None
    db_path = options[0][1]
    return db_path if isinstance(db_path, str) and db_path else None


def _pyrekordbox_db_path() -> Path | None:
    """Ask pyrekordbox's own config discovery for the db path."""
    try:
        from pyrekordbox.config import get_config
    except Exception:
        return None

    for program in ("rekordbox7", "rekordbox6"):
        try:
            cfg = get_config(program)
        except Exception:
            continue
        if cfg:
            db_path = cfg.get("db_path")
            if db_path:
                return Path(db_path)
    return None


def parse_options_value(text: str, key: str) -> str | None:
    """Return ``options[i][1]`` for the entry with ``options[i][0] == key``."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    options = data.get("options") if isinstance(data, dict) else None
    if not isinstance(options, list):
        return None
    for entry in options:
        if (
            isinstance(entry, list)
            and len(entry) >= 2
            and entry[0] == key
            and isinstance(entry[1], str)
        ):
            return entry[1]
    return None


def find_master_db(
    override: str | Path | None = None,
    *,
    platform: str | None = None,
    home: Path | None = None,
    appdata: str | None = None,
) -> tuple[Path, str]:
    """Resolve the path of the Rekordbox ``master.db``.

    Resolution order:
    1. explicit ``override`` (``--db-path`` CLI option),
    2. ``DJUTIL_RB_DB`` environment variable,
    3. pyrekordbox's own config discovery,
    4. ``options.json`` ``db-path``,
    5. ``master.db`` next to the ``share`` directory.

    The first candidate that exists on disk wins. Returns ``(path, source)``.
    """
    if override:
        return Path(override), "cli"
    env = os.environ.get(ENV_DB_PATH)
    if env:
        return Path(env), f"env:{ENV_DB_PATH}"

    candidates: list[tuple[Path, str]] = []
    found = _pyrekordbox_db_path()
    if found is not None:
        candidates.append((found, "pyrekordbox-config"))

    try:
        dirs = rekordbox_dirs(platform, home, appdata)
    except FileNotFoundError:
        dirs = None
    if dirs is not None:
        if dirs.options_json.exists():
            db_path = parse_options_value(
                dirs.options_json.read_text(encoding="utf-8"), "db-path"
            )
            if db_path:
                candidates.append((Path(db_path), "options.json"))
        candidates.append((dirs.share_dir.parent / "master.db", "default-location"))

    for path, source in candidates:
        if path.exists():
            return path, source

    tried = ", ".join(f"{p} ({s})" for p, s in candidates) or "none"
    raise FileNotFoundError(
        f"Could not locate the Rekordbox master.db (tried: {tried}). "
        f"Pass --db-path or set {ENV_DB_PATH}."
    )


def rekordbox_version(
    platform: str | None = None,
    home: Path | None = None,
    appdata: str | None = None,
) -> str | None:
    """Best-effort Rekordbox version: pyrekordbox config, then options.json."""
    try:
        from pyrekordbox.config import get_config

        for program in ("rekordbox7", "rekordbox6"):
            try:
                cfg = get_config(program)
            except Exception:
                continue
            if cfg and cfg.get("version"):
                return str(cfg["version"])
    except Exception:
        pass

    try:
        dirs = rekordbox_dirs(platform, home, appdata)
    except FileNotFoundError:
        return None
    if dirs.options_json.exists():
        try:
            return parse_options_value(
                dirs.options_json.read_text(encoding="utf-8"), "app_ver"
            )
        except OSError:
            return None
    return None


def share_dir(
    platform: str | None = None,
    home: Path | None = None,
    appdata: str | None = None,
) -> Path:
    """Directory Rekordbox uses for artwork images etc."""
    return rekordbox_dirs(platform, home, appdata).share_dir


ENV_AGENT_DATA_DIR = "DJUTIL_AGENT_DATA_DIR"


def agent_data_dir() -> Path:
    """Per-user data dir for the agent (logs, config, CSV exports)."""
    override = os.environ.get(ENV_AGENT_DATA_DIR)
    path = (
        Path(override)
        if override
        else Path(user_data_dir("DJUtil", appauthor=False))
    )
    path.mkdir(parents=True, exist_ok=True)
    return path
