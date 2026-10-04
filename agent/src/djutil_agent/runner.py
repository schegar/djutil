"""Shared engine loop used by `djutil-agent run` and the tray app."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from .config import AgentConfig, load_config
from .live.forwarder import LiveForwarder
from .live.outbox import Outbox
from .platform.paths import (
    agent_data_dir,
    find_master_db,
    rekordbox_dirs,
    rekordbox_version,
)
from .rekordbox.connection import RekordboxKeyError, open_rekordbox
from .rekordbox.reader import RekordboxReader
from .rekordbox.watcher import HistoryWatcher
from .status import AgentStatus

if TYPE_CHECKING:
    from .sync.engine import SyncEngine

logger = logging.getLogger(__name__)

POLL_INTERVAL = 30.0
RECONCILE_INTERVAL = 600.0


class AgentNotConfiguredError(Exception):
    pass


def build_engine(
    cfg: AgentConfig,
    db_path: Path | None = None,
    key: str | None = None,
) -> tuple[SyncEngine, Path]:
    """Build a SyncEngine + resolved db path. Raises on bad config/key."""
    from .sync.client import SyncClient
    from .sync.engine import SyncEngine

    if not cfg.configured:
        raise AgentNotConfiguredError(
            "Not configured. Run: djutil-agent configure --server URL "
            "--token TOKEN (or set DJUTIL_SERVER / DJUTIL_AGENT_TOKEN)"
        )
    path, _source = find_master_db(db_path)
    if not path.exists():
        raise FileNotFoundError(f"Rekordbox database not found: {path}")
    engine_db = open_rekordbox(path, key)  # raises RekordboxKeyError
    reader = RekordboxReader(engine_db)
    try:
        share = rekordbox_dirs().share_dir
    except FileNotFoundError:
        share = path.parent / "share"
    client = SyncClient(cfg.server, cfg.token)
    return (
        SyncEngine(
            reader,
            client,
            share,
            state_file=agent_data_dir() / "sync_fingerprints.json",
        ),
        path,
    )


def run_engine(
    status: AgentStatus,
    stop: threading.Event,
    *,
    db_path: Path | None = None,
    key: str | None = None,
    sync_now: threading.Event | None = None,
    full_sync: threading.Event | None = None,
    echo: Callable[[str], None] = print,
) -> None:
    """Run sync watcher + live forwarder until `stop` is set."""
    cfg = load_config()
    if not cfg.configured:
        status.set_configured(False)
        status.set_error(
            "Not configured – use Open config or `djutil-agent configure`"
        )
        raise AgentNotConfiguredError("agent is not configured")
    status.set_configured(True)
    try:
        engine, path = build_engine(cfg, db_path=db_path, key=key)
    except RekordboxKeyError as exc:
        status.set_error(str(exc))
        raise
    except Exception as exc:
        status.set_error(str(exc))
        raise

    def safe_delta() -> None:
        try:
            stats = engine.run_delta()
            status.mark_sync(ok=True)
            if sum(stats.values()):
                echo(f"delta sync: {stats}")
        except Exception as exc:
            status.mark_sync(ok=False, error=str(exc))
            logger.exception("delta sync failed")

    def safe_reconcile() -> None:
        try:
            stats = engine.reconcile_ids()
            status.mark_sync(ok=True)
            if sum(stats.values()):
                echo(f"reconcile: {stats}")
        except Exception as exc:
            status.mark_sync(ok=False, error=str(exc))
            logger.exception("reconcile failed")

    def safe_full() -> None:
        try:
            stats = engine.run_full()
            status.mark_sync(ok=True)
            echo(f"full sync: {stats}")
        except Exception as exc:
            status.mark_sync(ok=False, error=str(exc))
            logger.exception("full sync failed")

    try:
        if engine.server_empty():
            echo("Server state empty: running full sync")
            safe_reconcile()
            safe_full()
        else:
            safe_delta()
    except Exception:
        logger.exception("startup sync failed")

    forwarder: LiveForwarder | None = None
    live_thread: threading.Thread | None = None
    try:
        live_reader = RekordboxReader(open_rekordbox(path, key))
        deck_watcher = None
        if cfg.deck_reader:
            from .rbmem.deckwatch import DeckWatcher
            from .rbmem.scan import DbTrack, build_db_map

            def db_map(
                path: Path = path, key: str | None = key
            ) -> dict[str, DbTrack]:  # noqa: B008
                engine = open_rekordbox(path, key)
                try:
                    return build_db_map(
                        RekordboxReader(engine).analysis_index()
                    )
                finally:
                    engine.dispose()

            deck_watcher = DeckWatcher(db_map)
        forwarder = LiveForwarder(
            HistoryWatcher(live_reader),
            Outbox(agent_data_dir() / "outbox.db"),
            cfg.server,
            cfg.token,
            rb_version=rekordbox_version(),
            status=status,
            deck_watcher=deck_watcher,
            play_log=agent_data_dir() / "play_events.csv",
        )
        live_thread = threading.Thread(
            target=lambda: asyncio.run(forwarder.run()),
            name="live-forwarder",
            daemon=True,
        )
        live_thread.start()
        echo("Live play forwarding enabled.")
    except Exception:
        logger.exception("live forwarding unavailable; continuing without it")

    observer = None
    try:
        from .sync.watcher import watch_master_db

        observer = watch_master_db(path, safe_delta)
        echo(f"Watching {path} (fallback poll {POLL_INTERVAL:.0f} s).")
    except Exception:
        logger.exception("watchdog unavailable; using polling only")

    last_poll = time.monotonic()
    last_reconcile = time.monotonic()
    try:
        while not stop.is_set():
            if sync_now is not None and sync_now.is_set():
                sync_now.clear()
                safe_delta()
            if full_sync is not None and full_sync.is_set():
                full_sync.clear()
                safe_full()
            now = time.monotonic()
            if now - last_poll >= POLL_INTERVAL:
                last_poll = now
                safe_delta()
            if now - last_reconcile >= RECONCILE_INTERVAL:
                last_reconcile = now
                safe_reconcile()
            stop.wait(1)
    finally:
        if forwarder is not None:
            forwarder.stop()
        if live_thread is not None:
            live_thread.join(timeout=5)
        if observer is not None:
            observer.stop()
            observer.join(timeout=5)
        engine.client.close()
        status.set_connection("disconnected")
