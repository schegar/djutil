"""SQLite online backups with rotation (`python -m djutil_server backup`)."""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from pathlib import Path


def backup_name(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"djutil-{now:%Y%m%d-%H%M%S}.db"


def list_backups(dest_dir: Path) -> list[Path]:
    return sorted(dest_dir.glob("djutil-*.db"))


def rotate(dest_dir: Path, keep: int) -> list[Path]:
    """Delete all but the newest `keep` copies. Returns deleted paths."""
    backups = list_backups(dest_dir)
    deleted = []
    for old in backups[: max(0, len(backups) - keep)]:
        old.unlink()
        deleted.append(old)
    return deleted


def run_backup(db_path: Path, dest_dir: Path, keep: int) -> Path:
    """Online-backup `db_path` into dest_dir and verify the copy."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / backup_name()
    # Try read-only first (the backup service mounts the data volume ro);
    # fall back to a normal connection if the WAL needs recovery.
    try:
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        src = sqlite3.connect(db_path)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
            ok = dst.execute("PRAGMA integrity_check").fetchall()
        finally:
            dst.close()
    finally:
        src.close()
    if ok != [("ok",)]:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"integrity_check failed on {dest}: {ok[:3]}")
    rotate(dest_dir, keep)
    return dest


def backup_loop(db_path: Path, dest_dir: Path, keep: int, hours: float) -> None:
    while True:
        dest = run_backup(db_path, dest_dir, keep)
        print(f"backup written: {dest}", flush=True)
        time.sleep(hours * 3600)
