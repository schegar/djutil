import sqlalchemy
from sqlalchemy import create_engine, text

from djutil_agent.rekordbox.watcher import HistoryWatcher


def insert_history(db_file, rows):
    eng = create_engine(f"sqlite:///{db_file}")
    with eng.begin() as conn:
        for row in rows:
            conn.execute(
                text(
                    "INSERT INTO djmdSongHistory (ID, HistoryID, ContentID, "
                    "TrackNo, created_at) VALUES (:id,'h2',:cid,:no,:ts)"
                ),
                row,
            )
    eng.dispose()


def test_prime_emits_nothing(reader, db_file):
    watcher = HistoryWatcher(reader)
    watcher.prime()
    assert watcher.poll() == []


def test_new_rows_emitted_once_in_order(reader, db_file):
    watcher = HistoryWatcher(reader)
    watcher.prime()
    insert_history(
        db_file,
        [
            {"id": "sh4", "cid": "t2", "no": 2, "ts": "2024-01-06 21:05:00.000 +00:00"},
            {"id": "sh5", "cid": "t1", "no": 3, "ts": "2024-01-06 21:10:00.000 +00:00"},
        ],
    )
    events = watcher.poll()
    assert [e.history_entry_id for e in events] == ["sh4", "sh5"]
    assert events[0].track is not None and events[0].track.title == "Song Two"
    assert events[0].detected_at is not None
    assert watcher.poll() == []  # nothing new


def test_same_created_at_tie(reader, db_file):
    watcher = HistoryWatcher(reader)
    watcher.prime()
    ts = "2024-01-06 21:00:00.000 +00:00"  # same as existing sh3
    insert_history(db_file, [{"id": "sh9", "cid": "t2", "no": 9, "ts": ts}])
    events = watcher.poll()
    assert [e.history_entry_id for e in events] == ["sh9"]
    assert watcher.poll() == []


def test_database_locked_skips_cycle(reader, monkeypatch):
    watcher = HistoryWatcher(reader)
    watcher.prime()

    def boom(self):
        raise sqlalchemy.exc.OperationalError(
            "x", {}, Exception("database is locked")
        )

    monkeypatch.setattr(HistoryWatcher, "_history_rows", boom)
    assert watcher.poll() == []
