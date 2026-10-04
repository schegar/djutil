"""System-tray application: runs the agent engine in background threads.

The pystray loop must run on the main thread (macOS requirement); engine
work happens in daemon threads coordinated through AgentStatus.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

from . import __version__
from .config import AgentConfig, config_path, load_config, save_config
from .log_setup import logs_dir, setup_file_logging
from .platform import autostart
from .platform.paths import agent_data_dir
from .runner import run_engine
from .status import AgentStatus

logger = logging.getLogger(__name__)

_COLORS = {
    "green": "#22c55e",
    "amber": "#f59e0b",
    "red": "#ef4444",
}


def _icon_image(color: str) -> Any:
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((6, 6, 58, 58), fill=_COLORS[color], outline="#111111", width=3)
    return img


def _open_path(path: Path) -> None:
    """Open a file/dir with the OS default handler."""
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def _ensure_config() -> Path:
    path = config_path()
    if not path.exists():
        save_config(AgentConfig(server="https://djutil.example.com", token=""))
    return path


def _post(
    cfg: AgentConfig, path: str, body: dict[str, object] | None = None
) -> bool:
    import httpx

    try:
        r = httpx.post(
            f"{cfg.server}{path}",
            json=body or {},
            headers={"Authorization": f"Bearer {cfg.token}"},
            timeout=10,
        )
        return r.status_code in (200, 201)
    except Exception:
        logger.exception("recording control failed")
        return False


def run_tray() -> int:
    """Run the tray application on the main thread."""
    log_path = setup_file_logging()
    logger.info("tray starting (v%s), log: %s", __version__, log_path)

    import pystray

    status = AgentStatus()
    cfg = load_config()
    status.set_configured(cfg.configured)
    if not cfg.configured:
        status.set_error(
            "Not configured – use Open config or `djutil-agent configure`"
        )

    stop = threading.Event()
    sync_now = threading.Event()
    full_sync = threading.Event()
    worker: threading.Thread | None = None
    if cfg.configured:
        worker = threading.Thread(
            target=run_engine,
            kwargs={
                "status": status,
                "stop": stop,
                "sync_now": sync_now,
                "full_sync": full_sync,
                "echo": logger.info,
            },
            name="agent-engine",
            daemon=True,
        )
        worker.start()

    def refresh_agent_status() -> None:
        """Sync the recording flag with the server-side truth."""
        import httpx

        if not cfg.configured:
            return
        try:
            r = httpx.get(
                f"{cfg.server}/api/agent/status",
                headers={"Authorization": f"Bearer {cfg.token}"},
                timeout=10,
            )
            if r.status_code == 200:
                status.set_recording(bool(r.json().get("active_set")))
        except Exception:
            pass

    def on_open_djutil(icon: Any = None, item: Any = None) -> None:
        webbrowser.open(cfg.server)

    def on_sync_now(icon: Any = None, item: Any = None) -> None:
        sync_now.set()

    def on_full_sync(icon: Any = None, item: Any = None) -> None:
        full_sync.set()

    def on_toggle_recording(icon: Any = None, item: Any = None) -> None:
        if status.snapshot().recording:
            ok = _post(cfg, "/api/agent/sets/stop")
        else:
            ok = _post(cfg, "/api/agent/sets/start", {})
        if ok:
            status.set_recording(not status.snapshot().recording)
        refresh_agent_status()

    def on_toggle_autostart(icon: Any = None, item: Any = None) -> None:
        try:
            if autostart.is_enabled():
                autostart.disable()
            else:
                autostart.enable()
        except Exception:
            logger.exception("autostart toggle failed")

    def on_open_logs(icon: Any = None, item: Any = None) -> None:
        _open_path(logs_dir())

    def on_open_config(icon: Any = None, item: Any = None) -> None:
        _open_path(_ensure_config())

    def on_quit(icon: Any = None, item: Any = None) -> None:
        stop.set()
        icon.stop()

    def recording_label(item: Any) -> str:
        return (
            "Stop recording"
            if status.snapshot().recording
            else "Start recording"
        )

    def status_label(item: Any) -> str:
        return status.snapshot().status_line()

    icon = pystray.Icon(
        "djutil-agent",
        _icon_image(status.snapshot().icon_color()),
        f"DJUtil Agent {__version__}",
        menu=pystray.Menu(
            pystray.MenuItem(status_label, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open DJUtil", on_open_djutil),
            pystray.MenuItem("Sync now", on_sync_now),
            pystray.MenuItem("Full sync", on_full_sync),
            pystray.MenuItem(recording_label, on_toggle_recording),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Start at login",
                on_toggle_autostart,
                checked=lambda item: autostart.is_enabled(),
            ),
            pystray.MenuItem("Open logs folder", on_open_logs),
            pystray.MenuItem("Open config", on_open_config),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", on_quit),
        ),
    )

    def refresh_loop() -> None:
        n = 0
        while not stop.wait(2.0):
            n += 1
            try:
                color = status.snapshot().icon_color()
                icon.icon = _icon_image(color)
                icon.update_menu()
                if n % 8 == 0:  # ~every 16 s
                    refresh_agent_status()
            except Exception:
                pass

    threading.Thread(target=refresh_loop, name="tray-refresh", daemon=True).start()

    try:
        icon.run()
    finally:
        stop.set()
        if worker is not None:
            worker.join(timeout=10)
    logger.info("tray exiting")
    return 0


def load_config_json() -> dict[str, Any]:
    path = config_path()
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


# convenience used by tests / smoke checks
def data_dir() -> Path:
    return agent_data_dir()
