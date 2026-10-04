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
    from djutil_agent.rbmem.process import WindowsProcess
    from djutil_agent.rbmem.scan import DbTrack
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


decks_app = typer.Typer(
    help="Read deck state from Rekordbox process memory (Windows, read-only)."
)
app.add_typer(decks_app, name="decks")


def _open_rekordbox_process() -> WindowsProcess:
    from djutil_agent.rbmem.process import (
        ProcessNotFoundError,
        UnsupportedPlatform,
        WindowsProcess,
    )

    try:
        proc = WindowsProcess()
    except UnsupportedPlatform as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(2) from exc
    except ProcessNotFoundError as exc:
        typer.secho(
            "rekordbox.exe is not running - start Rekordbox, load tracks "
            "on at least one (ideally two) decks, then retry.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(2) from exc
    except Exception as exc:
        typer.secho(f"could not open Rekordbox process: {exc}",
                    fg=typer.colors.RED)
        raise typer.Exit(2) from exc
    return proc


def _deck_db_map() -> dict[str, DbTrack]:
    from djutil_agent.rbmem.scan import build_db_map

    reader = _reader()
    return build_db_map(reader.analysis_index())


@decks_app.command("scan")
def decks_scan(
    save: bool = typer.Option(True, "--save/--no-save"),
) -> None:
    """Discover memory pointer chains for the running Rekordbox version."""
    from djutil_agent.rbmem.offsets import BUILTIN_BASES, save_offsets
    from djutil_agent.rbmem.scan import scan

    proc = _open_rekordbox_process()
    version = proc.version or _rekordbox_version() or "unknown"
    typer.echo(
        f"Rekordbox {version} (pid {proc.pid}, "
        f"module @{proc.module_base:#x}, {proc.module_size / 1e6:.0f} MB)"
    )
    db = _deck_db_map()
    typer.echo(f"{len(db)} tracks with analysis paths in master.db")

    result = scan(proc, db, bases=BUILTIN_BASES)
    for note in result.notes:
        typer.echo(note)
    typer.echo(
        f"scan took {result.elapsed_s:.1f}s; candidates: "
        + ", ".join(f"{k}={v}" for k, v in result.candidates.items())
    )
    offs = result.offsets()
    if offs is None:
        typer.secho("no anchor found - nothing discovered",
                    fg=typer.colors.RED)
        raise typer.Exit(3)
    typer.echo("\nDiscovered chains (rkbx_link format):")
    if offs.master_index:
        typer.echo(f"  master_index: {offs.master_index.format()}")
    for name in ("anlz_path", "track_info", "bpm", "position"):
        ptrs = getattr(offs, name)
        if not ptrs:
            typer.echo(f"  {name}: not found")
            continue
        for d, p in enumerate(ptrs):
            typer.echo(f"  {name}[{d}]: {p.format()}")
    if save:
        from djutil_agent.rbmem.offsets import load_offsets

        # don't clobber a master_index found by `decks master-scan`
        existing = load_offsets(version)
        if (
            offs.master_index is None
            and existing is not None
            and existing.master_index is not None
        ):
            offs.master_index = existing.master_index
        path = save_offsets(version, offs)
        typer.echo(f"\nSaved to {path}")


@decks_app.command("master-scan")
def decks_master_scan() -> None:
    """Interactively discover the master-deck-index chain (press MASTER on
    decks 1/2 when prompted)."""
    from djutil_agent.rbmem.master import master_scan, save_master_index

    proc = _open_rekordbox_process()
    version = proc.version or _rekordbox_version() or "unknown"
    typer.echo(
        f"Rekordbox {version} (pid {proc.pid}, "
        f"module @{proc.module_base:#x})"
    )
    slot, fallback = master_scan(proc, echo=typer.echo)
    if slot is None and not fallback:
        raise typer.Exit(3)
    if slot is not None:
        typer.echo(f"\nmaster_index chain: {slot:X} 20 278 124")
    else:
        typer.echo("\ndifferential survivors (direct statics, `X 0`):")
        for off in fallback:
            typer.echo(f"  {off:X} 0   (module+{off:#x})")
        if len(fallback) != 1:
            typer.echo(
                "more than one survivor - not saving; re-run after pressing "
                "MASTER a few times"
            )
            raise typer.Exit(3)
    if save_master_index(
        version,
        slot,
        fallback[0] if slot is None and len(fallback) == 1 else None,
        echo=typer.echo,
    ):
        typer.echo("Saved.")


@decks_app.command("watch")
def decks_watch(
    hz: float = typer.Option(5.0, "--hz", min=0.5, max=30),
    seconds: float = typer.Option(
        0.0, "--seconds", help="Stop after N seconds (0 = unlimited)"
    ),
) -> None:
    """Print live deck state (title/BPM/position) until Ctrl+C."""
    import contextlib

    from djutil_agent.rbmem.master import DeckSnap, pick_now_playing
    from djutil_agent.rbmem.offsets import SAMPLE_RATE, load_offsets
    from djutil_agent.rbmem.pointer import (
        read_cstr,
        read_f32,
        read_i64,
        read_u8,
    )
    from djutil_agent.rbmem.process import MemoryReadError
    from djutil_agent.rbmem.scan import norm_anlz_path

    proc = _open_rekordbox_process()
    version = proc.version or _rekordbox_version() or ""
    offs = load_offsets(version)
    if offs is None or offs.anlz_path is None:
        typer.secho(
            f"No memory offsets for Rekordbox {version or 'unknown'} - "
            "run `djutil-agent decks scan` first.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    db = _deck_db_map()

    typer.echo(
        f"Watching {len(offs.anlz_path)} decks at {hz:g} Hz "
        f"(offsets for {version}). Ctrl+C to stop."
    )
    if offs.master_index is None:
        typer.echo("master index unknown - run `djutil-agent decks master-scan`")
    prev: dict[int, tuple[str | None, float]] = {}
    snaps: dict[int, DeckSnap] = {}
    prev_line = ""
    prev_np: tuple[int | None, str | None] = (None, None)
    t_start = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            parts = []
            master = None
            if offs.master_index:
                with contextlib.suppress(MemoryReadError):
                    master = read_u8(proc, offs.master_index)
            for d in range(len(offs.anlz_path)):
                try:
                    raw = read_cstr(proc, offs.anlz_path[d], 500)
                except MemoryReadError:
                    continue
                norm = norm_anlz_path(raw)
                track = db.get(norm) if norm else None
                title = None
                if offs.track_info:
                    with contextlib.suppress(MemoryReadError):
                        info = read_cstr(proc, offs.track_info[d], 200)
                        title = info.split("\n")[0].strip() or None
                title = title or (track.title if track else "?")
                bpm = pos = None
                if offs.bpm:
                    with contextlib.suppress(MemoryReadError):
                        bpm = read_f32(proc, offs.bpm[d])
                if offs.position:
                    with contextlib.suppress(MemoryReadError):
                        pos = read_i64(proc, offs.position[d])
                playing = (
                    pos is not None
                    and d in prev
                    and prev[d][1] is not None
                    and pos != prev[d][1]
                )
                prev[d] = (norm, pos or 0.0)
                cid = track.content_id if track else None
                snap = snaps.get(d)
                if snap is None:
                    snap = DeckSnap(False, None, None, "")
                if playing:
                    if not snap.playing:
                        snap.playing_since = now
                    snap.playing = True
                else:
                    snap.playing = False
                    snap.playing_since = None
                snap.content_id = cid
                snap.title = title or "?"
                snaps[d] = snap
                mark = "*" if master == d else " "
                pos_s = f"{pos / SAMPLE_RATE:.2f}s" if pos is not None else "?"
                parts.append(
                    f"{mark}d{d} {'PLAY' if playing else '    '} "
                    f"{title} bpm={bpm if bpm is not None else '?'} "
                    f"pos={pos_s} cid={cid or '-'}"
                )
            assert offs.anlz_path is not None
            np_idx = pick_now_playing(
                [
                    snaps.get(d, DeckSnap(False, None, None, ""))
                    for d in range(len(offs.anlz_path))
                ],
                master,
                now,
            )
            np_state: tuple[int | None, str | None] = (None, None)
            if np_idx is not None:
                snap = snaps[np_idx]
                np_state = (np_idx, snap.content_id)
            if np_state != prev_np and np_state[0] is not None:
                snap = snaps[np_state[0]]
                typer.echo(
                    f"{time.strftime('%H:%M:%S')} NOW PLAYING: {snap.title} "
                    f"[{snap.content_id}] (deck {np_state[0]})"
                )
            prev_np = np_state
            line = " | ".join(parts)
            if line and line != prev_line:
                typer.echo(
                    f"{time.strftime('%H:%M:%S')} master={master} {line}"
                )
                prev_line = line
            time.sleep(1.0 / hz)
            if seconds and now - t_start >= seconds:
                break
    except KeyboardInterrupt:
        typer.echo("\nStopped.")


@decks_app.command("probe")
def decks_probe(
    track: list[str] | None = typer.Option(
        None, "--track", help="Seed only tracks matching this content id or "
        "title substring (repeatable)"
    ),
    absolute_only: bool = typer.Option(
        False, "--absolute-only", help="Seed only absolute (C:/...) paths"
    ),
    diff: bool = typer.Option(
        False, "--diff", help="Snapshot, prompt to load a new track, "
        "seed only new/changed strings"
    ),
    frontier: int = typer.Option(2000, "--frontier"),
    depth: int = typer.Option(4, "--depth"),
    out: Path | None = typer.Option(
        None, "--out", help="Also write the report to this file"
    ),
) -> None:
    """Diagnostic: find ANLZ strings in memory and walk pointers back to the
    module (used when `decks scan` finds nothing)."""
    from djutil_agent.rbmem.probe import run

    proc = _open_rekordbox_process()
    typer.echo(
        f"Rekordbox {proc.version or _rekordbox_version() or '?'} "
        f"(pid {proc.pid}, module @{proc.module_base:#x}, "
        f"{proc.module_size / 1e6:.0f} MB)"
    )
    db = _deck_db_map()
    typer.echo(f"{len(db)} tracks with analysis paths in master.db")

    fh = out.open("w", encoding="utf-8") if out is not None else None

    def echo(msg: str) -> None:
        typer.echo(msg)
        if fh is not None:
            fh.write(msg + "\n")
            fh.flush()

    try:
        run(
            proc,
            db,
            echo=echo,
            depth=depth,
            cap=frontier,
            absolute_only=absolute_only,
            track_filters=tuple(track or ()),
            diff=diff,
        )
    finally:
        if fh is not None:
            fh.close()


if __name__ == "__main__":
    sys.exit(app())
