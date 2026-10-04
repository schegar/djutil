"""djutil-agent command line interface."""

from __future__ import annotations

import csv
import logging
import platform
import sys
import time
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from djutil_agent import __version__
from djutil_agent.config import AgentConfig, load_config, save_config
from djutil_agent.platform.paths import (
    agent_data_dir,
    find_master_db,
    rekordbox_dirs,
    rekordbox_version,
)
from djutil_agent.rekordbox.connection import ENV_KEY, RekordboxKeyError, open_rekordbox
from djutil_agent.rekordbox.reader import RekordboxReader
from djutil_agent.rekordbox.watcher import HistoryWatcher

app = typer.Typer(help="DJUtil Rekordbox 6/7 integration agent.")

logger = logging.getLogger("djutil_agent")

if TYPE_CHECKING:
    from djutil_agent.sync.engine import SyncEngine


class _State:
    db_path: Path | None = None
    db_source: str = ""
    key: str | None = None


_state = _State()


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"djutil-agent {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    db_path: Path | None = typer.Option(
        None, "--db-path", help="Path to the Rekordbox master.db"
    ),
    key: str | None = typer.Option(
        None, "--key", help=f"SQLCipher key (or set {ENV_KEY})"
    ),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Verbose logging"),
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True
    ),
) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    import contextlib

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(ValueError):
                reconfigure(encoding="utf-8", errors="replace")
    _state.db_path = db_path
    _state.key = key


def _resolve_db() -> Path:
    path, source = find_master_db(_state.db_path)
    _state.db_source = source
    if not path.exists():
        typer.secho(f"Database not found: {path} (via {source})", fg=typer.colors.RED)
        raise typer.Exit(2)
    return path


def _reader() -> RekordboxReader:
    db_path = _resolve_db()
    try:
        engine = open_rekordbox(db_path, _state.key)
    except RekordboxKeyError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(3) from exc
    return RekordboxReader(engine)


def _rekordbox_version() -> str | None:
    return rekordbox_version()


@app.command()
def check() -> None:
    """Verify the Rekordbox database can be opened and show summary info."""
    import pyrekordbox

    typer.echo(f"djutil-agent {__version__}")
    typer.echo(f"OS: {platform.system()} {platform.release()} ({platform.machine()})")
    typer.echo(f"pyrekordbox: {pyrekordbox.__version__}")

    rb_version = _rekordbox_version()
    typer.echo(f"Rekordbox version: {rb_version or 'unknown'}")

    db_path = _resolve_db()
    typer.echo(f"Database: {db_path} (via {_state.db_source})")
    try:
        dirs = rekordbox_dirs()
        typer.echo(f"Share dir: {dirs.share_dir}")
    except FileNotFoundError:
        pass

    reader = _reader()

    counts = reader.counts()
    typer.echo("\nCounts:")
    for name, n in counts.items():
        typer.echo(f"  {name}: {n}")

    tracks = reader.tracks()
    if tracks:
        typer.echo("\nSample track:")
        typer.echo(tracks[0].model_dump_json(indent=2))

    typer.echo("\nLatest history entries:")
    entries = reader.history_entries()
    for e in entries[-5:]:
        track = reader.track(e.content_id)
        title = f"{track.artist} - {track.title}" if track else e.content_id
        typer.echo(f"  [{e.created_at}] {title} (content {e.content_id})")


@app.command()
def dump(
    out: Path = typer.Option(..., "--out", help="Output JSON file"),
    include_deleted: bool = typer.Option(False, "--include-deleted"),
) -> None:
    """Export the whole library to a JSON file."""
    db_path = _resolve_db()
    reader = _reader()
    snap = reader.snapshot(
        db_path=db_path,
        rekordbox_version=_rekordbox_version(),
        include_deleted=include_deleted,
    )
    out.write_text(snap.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(f"Wrote snapshot with {len(snap.tracks)} tracks to {out}")


@app.command()
def watch(interval: float = typer.Option(1.0, "--interval", min=0.2)) -> None:
    """Print new Rekordbox history rows live (Ctrl+C to stop)."""
    reader = _reader()
    watcher = HistoryWatcher(reader)
    watcher.prime()

    log_path = agent_data_dir() / "play_events.csv"
    new_file = not log_path.exists()
    log_file = log_path.open("a", newline="", encoding="utf-8")
    writer = csv.writer(log_file)
    if new_file:
        writer.writerow(
            [
                "detected_at",
                "played_at",
                "latency_s",
                "history_entry_id",
                "history_id",
                "content_id",
                "artist",
                "title",
            ]
        )
        log_file.flush()

    typer.echo(f"Watching for new plays (log: {log_path}). Ctrl+C to stop.")
    try:
        while True:
            events = watcher.poll()
            for ev in events:
                t = ev.track
                artist = t.artist if t else "?"
                title = t.title if t else "?"
                mix = f" ({t.mix})" if t and t.mix else ""
                bpm = f"{t.bpm:.0f}" if t and t.bpm else "?"
                key = t.camelot or t.key_name or "?" if t else "?"
                latency = (
                    (ev.detected_at - ev.played_at).total_seconds()
                    if ev.played_at
                    else None
                )
                played = (
                    ev.played_at.astimezone(UTC).isoformat()
                    if ev.played_at
                    else ""
                )
                lat = f"{latency:.1f}s" if latency is not None else "?"
                typer.echo(
                    f"{ev.detected_at.isoformat(timespec='seconds')} "
                    f"played={played} latency={lat} "
                    f"{artist} - {title}{mix} [{bpm} BPM, {key}] "
                    f"content={ev.content_id}"
                )
                writer.writerow(
                    [
                        ev.detected_at.isoformat(),
                        played,
                        f"{latency:.3f}" if latency is not None else "",
                        ev.history_entry_id,
                        ev.history_id,
                        ev.content_id,
                        artist,
                        title,
                    ]
                )
                log_file.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        typer.echo("\nStopped.")
    finally:
        log_file.close()


def _sync_engine() -> tuple[SyncEngine, Path]:
    from djutil_agent.sync.client import SyncClient
    from djutil_agent.sync.engine import SyncEngine

    cfg = load_config()
    if not cfg.configured:
        typer.secho(
            "Not configured. Run: djutil-agent configure --server URL "
            "--token TOKEN (or set DJUTIL_SERVER / DJUTIL_AGENT_TOKEN)",
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    db_path = _resolve_db()
    reader = _reader()
    try:
        share = rekordbox_dirs().share_dir
    except FileNotFoundError:
        share = db_path.parent / "share"
    client = SyncClient(cfg.server, cfg.token)
    return (
        SyncEngine(
            reader,
            client,
            share,
            state_file=agent_data_dir() / "sync_fingerprints.json",
        ),
        db_path,
    )


@app.command()
def configure(
    server: str = typer.Option(..., "--server", help="Server base URL"),
    token: str = typer.Option(..., "--token", help="Agent bearer token"),
) -> None:
    """Store the server URL and agent token in the agent data dir."""
    path = save_config(AgentConfig(server=server, token=token))
    typer.echo(f"Wrote {path}")


@app.command()
def sync(
    full: bool = typer.Option(
        False, "--full", help="Full sync + id reconciliation"
    ),
) -> None:
    """One-shot library sync to the server."""
    engine, _ = _sync_engine()
    try:
        stats = engine.run_full() if full else engine.run_delta()
    except Exception as exc:
        typer.secho(f"Sync failed: {exc}", fg=typer.colors.RED)
        raise typer.Exit(3) from exc
    finally:
        engine.client.close()
    for entity, n in stats.items():
        typer.echo(f"  {entity}: {n}")


@app.command()
def run() -> None:
    """Continuous sync: watch master.db and keep the server up to date."""
    from djutil_agent.log_setup import setup_file_logging
    from djutil_agent.runner import run_engine
    from djutil_agent.status import AgentStatus

    log_path = setup_file_logging(verbose=logger.isEnabledFor(logging.DEBUG))
    typer.echo(f"Logging to {log_path}")

    import threading

    stop = threading.Event()
    try:
        run_engine(
            AgentStatus(),
            stop,
            db_path=_state.db_path,
            key=_state.key,
            echo=typer.echo,
        )
    except KeyboardInterrupt:
        typer.echo("\nStopped.")
        stop.set()


@app.command()
def tray() -> None:
    """Run the agent as a system-tray application (engine in background)."""
    from djutil_agent.tray import run_tray

    raise typer.Exit(run_tray())


autostart_app = typer.Typer(help="Manage 'start at login' for the tray agent.")
app.add_typer(autostart_app, name="autostart")


@autostart_app.command("enable")
def autostart_enable() -> None:
    """Register the tray agent to start at login."""
    from djutil_agent.platform import autostart

    try:
        autostart.enable()
    except NotImplementedError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(2) from exc
    typer.echo(f"Autostart enabled: {autostart.status_value()}")


@autostart_app.command("disable")
def autostart_disable() -> None:
    """Remove the login registration."""
    from djutil_agent.platform import autostart

    try:
        autostart.disable()
    except NotImplementedError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(2) from exc
    typer.echo("Autostart disabled.")


@autostart_app.command("status")
def autostart_status() -> None:
    """Show whether the agent starts at login."""
    from djutil_agent.platform import autostart

    value = autostart.status_value()
    if value:
        typer.echo(f"enabled: {value}")
    else:
        typer.echo("disabled")


if __name__ == "__main__":
    sys.exit(app())
