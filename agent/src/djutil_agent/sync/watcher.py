"""Filesystem watcher for master.db changes (debounced) + fallback poll."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from watchdog.observers.api import BaseObserver


class Debouncer:
    """Calls ``callback`` once, ``delay`` seconds after the last ``notify()``."""

    def __init__(self, delay: float, callback: Callable[[], None]) -> None:
        self.delay = delay
        self.callback = callback
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def notify(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.delay, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        with self._lock:
            self._timer = None
        self.callback()

    def cancel(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


def watch_master_db(db_path: Path, on_change: Callable[[], None]) -> BaseObserver:
    """Watch ``master.db*`` (incl. WAL files) in its directory, debounced 3 s."""
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer  # noqa: TC002

    debouncer = Debouncer(3.0, on_change)

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event: object) -> None:
            src = getattr(event, "src_path", "")
            if src and Path(src).name.startswith(db_path.name):
                debouncer.notify()

    observer = Observer()
    observer.schedule(Handler(), str(db_path.parent), recursive=False)
    observer.daemon = True
    observer.start()
    return observer
