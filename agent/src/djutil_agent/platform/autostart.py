"""Cross-platform 'start at login' registration for the tray agent.

Windows: HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\DJUtilAgent.
macOS:   ~/Library/LaunchAgents/com.djutil.agent.plist + launchctl bootstrap.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path
from typing import Any

from .paths import agent_data_dir

RUN_VALUE = "DJUtilAgent"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
PLIST_LABEL = "com.djutil.agent"


def _target_args() -> list[str]:
    """Command used to launch the tray at login."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "tray"]
    return [sys.executable, "-m", "djutil_agent", "tray"]


def _command_line() -> str:
    return subprocess.list2cmdline(_target_args())


def _logs_dir() -> Path:
    d = agent_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def supported() -> bool:
    return sys.platform in ("win32", "darwin")


# -- macOS -------------------------------------------------------------------


def _plist_path(home: Path | None = None) -> Path:
    home = home or Path.home()
    return home / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"


def _plist_dict() -> dict[str, object]:
    logs = _logs_dir()
    return {
        "Label": PLIST_LABEL,
        "ProgramArguments": _target_args(),
        "RunAtLoad": True,
        "KeepAlive": False,
        "StandardOutPath": str(logs / "autostart.out.log"),
        "StandardErrorPath": str(logs / "autostart.err.log"),
    }


def _uid() -> int:
    # Only called on macOS, where getuid exists.
    return int(os.getuid())  # type: ignore[attr-defined]


def _mac_enable() -> None:
    path = _plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        plistlib.dump(_plist_dict(), f)
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{_uid()}", str(path)], check=False
    )


def _mac_disable() -> None:
    subprocess.run(
        ["launchctl", "bootout", f"gui/{_uid()}/{PLIST_LABEL}"], check=False
    )
    _plist_path().unlink(missing_ok=True)


def _mac_enabled() -> bool:
    return _plist_path().exists()


# -- Windows -----------------------------------------------------------------


def _winreg() -> Any:  # mockable seam (winreg only exists on Windows)
    import winreg

    return winreg


def _win_enabled() -> bool:
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE)
        return bool(value)
    except OSError:
        return False


def _win_enable() -> None:
    winreg = _winreg()
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, _command_line())


def _win_disable() -> None:
    winreg = _winreg()
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, RUN_VALUE)
    except OSError:
        pass


def _win_status() -> str | None:
    winreg = _winreg()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE)
        return str(value)
    except OSError:
        return None


# -- public API ----------------------------------------------------------------


def is_enabled() -> bool:
    if sys.platform == "win32":
        return _win_enabled()
    if sys.platform == "darwin":
        return _mac_enabled()
    return False


def status_value() -> str | None:
    """The registered command (Windows) or plist path (macOS), if enabled."""
    if sys.platform == "win32":
        return _win_status()
    if sys.platform == "darwin":
        path = _plist_path()
        return str(path) if path.exists() else None
    return None


def enable() -> None:
    if sys.platform == "win32":
        _win_enable()
    elif sys.platform == "darwin":
        _mac_enable()
    else:
        raise NotImplementedError(f"autostart not supported on {sys.platform}")


def disable() -> None:
    if sys.platform == "win32":
        _win_disable()
    elif sys.platform == "darwin":
        _mac_disable()
    else:
        raise NotImplementedError(f"autostart not supported on {sys.platform}")
