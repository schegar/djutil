"""Backup CLI: valid copies, rotation, concurrent-write integrity."""

import sqlite3
import threading
import time

from djutil_server.backup import list_backups, run_backup


def _make_db(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [(f"row{i}",) for i in range(50)])
    conn.commit()
    return conn


def test_backup_produces_valid_db(tmp_path):
    src = tmp_path / "src.db"
    conn = _make_db(src)
    dest_dir = tmp_path / "backups"
    dest = run_backup(src, dest_dir, keep=5)
    assert dest.exists()
    check = sqlite3.connect(dest)
    assert check.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert check.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 50
    check.close()
    conn.close()


def test_rotation_keeps_n(tmp_path):
    src = tmp_path / "src.db"
    conn = _make_db(src)
    dest_dir = tmp_path / "backups"
    for _i in range(6):
        run_backup(src, dest_dir, keep=3)
        # unique names: filenames are second-resolution
        time.sleep(1.01)
    assert len(list_backups(dest_dir)) == 3
    conn.close()


def test_backup_during_concurrent_write(tmp_path):
    src = tmp_path / "src.db"
    conn = _make_db(src)
    stop = threading.Event()
    errors = []

    def writer():
        w = sqlite3.connect(src, timeout=10)
        n = 0
        while not stop.is_set():
            try:
                w.execute("INSERT INTO t (v) VALUES (?)", (f"w{n}",))
                w.commit()
                n += 1
            except sqlite3.OperationalError:
                continue  # transient lock contention is fine
            except Exception as e:  # pragma: no cover - surface in assert
                errors.append(e)
                return
        w.close()

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    dest = run_backup(src, tmp_path / "backups", keep=5)
    stop.set()
    t.join(timeout=5)
    assert not errors
    check = sqlite3.connect(dest)
    assert check.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    check.close()
    conn.close()
