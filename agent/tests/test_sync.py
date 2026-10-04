"""SyncEngine against the real FastAPI app via httpx ASGI transport."""

import hashlib
import json

import pytest
from argon2 import PasswordHasher
from djutil_server.app import create_app
from djutil_server.config import Settings
from sqlalchemy import create_engine, text

from djutil_agent.sync.client import SyncClient
from djutil_agent.sync.engine import SyncEngine

TOKEN = "tok"


@pytest.fixture()
def server_settings(tmp_path):
    return Settings(
        data_dir=tmp_path / "srv",
        admin_password_hash=PasswordHasher().hash("pw"),
        agent_token=TOKEN,
        session_secret="s",
        cookie_secure=False,
    )


@pytest.fixture()
def server_url(server_settings):
    """Run the FastAPI app in a real uvicorn thread."""
    import socket
    import threading
    import time

    import uvicorn

    app = create_app(server_settings)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture()
def server_client(server_url):
    client = SyncClient(server_url, TOKEN, max_retries=0)
    yield client
    client.close()


@pytest.fixture()
def share_dir(tmp_path):
    d = tmp_path / "share"
    (d / "art").mkdir(parents=True)
    (d / "art" / "t1.jpg").write_bytes(b"fake-jpeg-t1")
    return d


@pytest.fixture()
def engine_sync(reader, server_client, share_dir):
    return SyncEngine(reader, server_client, share_dir)


def test_full_sync_counts(engine_sync, server_client):
    stats = engine_sync.run_full()
    assert stats["tracks"] == 3  # 2 upserts + 1 delete (t3)
    assert stats["playlists"] == 3
    assert stats["history_entries"] == 3
    state = server_client.get_state()
    assert state["tracks"] == 12  # max track usn


def test_delta_sends_only_changed(engine_sync, server_client, db_file):
    engine_sync.run_full()
    eng = create_engine(f"sqlite:///{db_file}")
    with eng.begin() as conn:
        conn.execute(
            text(
                "UPDATE djmdContent SET Title='Renamed', rb_local_usn=99"
                " WHERE ID='t1'"
            )
        )
    stats = engine_sync.run_delta()
    assert stats["tracks"] == 1
    assert stats["cues"] == 0
    assert server_client.get_state()["tracks"] == 99


def test_track_soft_delete(engine_sync, server_client, db_file,
                           server_settings):
    engine_sync.run_full()
    eng = create_engine(f"sqlite:///{db_file}")
    with eng.begin() as conn:
        conn.execute(
            text(
                "UPDATE djmdContent SET rb_local_deleted=1, rb_local_usn=101"
                " WHERE ID='t2'"
            )
        )
    engine_sync.run_delta()
    import sqlite3

    sconn = sqlite3.connect(server_settings.db_path)
    deleted = sconn.execute(
        "SELECT deleted FROM tracks WHERE id='t2'"
    ).fetchone()[0]
    sconn.close()
    assert deleted == 1


def test_reconcile_removes_playlist(engine_sync, server_client, db_file):
    engine_sync.run_full()
    eng = create_engine(f"sqlite:///{db_file}")
    with eng.begin() as conn:
        conn.execute(
            text("DELETE FROM djmdPlaylist WHERE ID='pl2'")
        )
    stats = engine_sync.reconcile_ids()
    assert stats["playlists"] == 1


@pytest.fixture()
def no_usn_reader(db_file):
    """Reader over a DB whose djmdCue.rb_local_usn is all NULL (RB7-style)."""
    from djutil_agent.rekordbox.reader import RekordboxReader

    eng = create_engine(f"sqlite:///{db_file}")
    with eng.begin() as conn:
        conn.execute(text("UPDATE djmdCue SET rb_local_usn=NULL"))
    r = RekordboxReader(eng)
    yield r
    eng.dispose()


def test_second_delta_skips_unchanged_cues(no_usn_reader, server_client,
                                         tmp_path):
    eng = SyncEngine(
        no_usn_reader, server_client, state_file=tmp_path / "fps.json"
    )
    assert eng.run_delta()["cues"] == 3
    assert eng.run_delta()["cues"] == 0  # fingerprint match -> skip


def test_fingerprint_scoped_to_server(no_usn_reader, server_client,
                                      server_url, tmp_path):
    state_file = tmp_path / "fps.json"
    eng = SyncEngine(no_usn_reader, server_client, state_file=state_file)
    eng.run_delta()
    # a different server base_url must not reuse the stored fingerprint
    other = SyncClient(
        server_url.replace("127.0.0.1", "localhost"), TOKEN, max_retries=0
    )
    try:
        eng2 = SyncEngine(no_usn_reader, other, state_file=state_file)
        assert eng2.run_delta()["cues"] == 3
    finally:
        other.close()


def test_run_full_bypasses_fingerprint(no_usn_reader, server_client, tmp_path):
    eng = SyncEngine(
        no_usn_reader, server_client, state_file=tmp_path / "fps.json"
    )
    eng.run_full()
    # second full re-sends no-usn entities even though the fingerprint matches
    assert eng.run_full()["cues"] == 3


def test_legacy_flat_state_file(no_usn_reader, server_client, tmp_path):
    state_file = tmp_path / "fps.json"
    state_file.write_text(json.dumps({"cues": "deadbeef"}))  # old format
    eng = SyncEngine(no_usn_reader, server_client, state_file=state_file)
    assert eng.run_delta()["cues"] == 3  # treated as empty -> send
    data = json.loads(state_file.read_text())
    assert isinstance(data.get(server_client.base_url), dict)


def test_artwork_uploaded_once(engine_sync, server_client, tmp_path):
    engine_sync.run_full()
    # verify via a HEAD on the known hash
    expected = hashlib.sha256(b"fake-jpeg-t1").hexdigest()
    assert server_client.artwork_exists(expected)
    # second sync must not re-upload
    engine_sync._known_artwork.clear()  # simulate restart
    track = engine_sync.reader.track("t1")
    engine_sync._prepare_track(track)
    assert expected in engine_sync._known_artwork
