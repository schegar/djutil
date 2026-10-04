"""Live ingestion, sets, suggestions and websocket tests."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from conftest import PASSWORD, batch, sample_track  # noqa: F401 - pytest sees it


def ev(i, tid="t1", minutes=0, base=None):
    played = (base or datetime(2026, 10, 1, 20, 0, tzinfo=UTC)) + timedelta(minutes=minutes)
    return {
        "history_entry_id": f"he-{i}",
        "history_id": "h1",
        "content_id": tid,
        "played_at": played.isoformat(),
        "detected_at": played.isoformat(),
    }


@pytest.fixture()
def seeded(agent):
    agent.post("/api/sync/batch", json=batch(
        "tracks", [
            sample_track("t1", camelot="8A", bpm=128.0, genre="Techno"),
            sample_track("t2", title="Next One", camelot="9A", bpm=130.0,
                         genre="Techno"),
            sample_track("t3", title="Far Away", camelot="4A", bpm=96.0,
                         genre="House"),
        ], max_usn=1))
    agent.post("/api/auth/login", json={"password": PASSWORD})
    return agent


def test_rest_events_ingest_and_live_state(seeded):
    r = seeded.post("/api/agent/events",
                    json=[ev(1, "t1"), ev(2, "t2", 4)])
    assert r.status_code == 200
    assert r.json()["ingested"] == 2
    st = seeded.get("/api/live/state").json()
    assert st["now_playing"]["id"] == "t2"
    assert len(st["session"]) == 2
    assert st["active_set"] is not None and st["active_set"]["auto"] is True
    # idempotent
    r = seeded.post("/api/agent/events", json=[ev(1, "t1")])
    assert r.json()["ingested"] == 0


def test_ingest_upserts_missing_track(seeded):
    event = ev(1, "missing")
    event["track"] = sample_track("missing", title="Late Sync")
    seeded.post("/api/agent/events", json=[event])
    assert seeded.get("/api/tracks/missing").json()["title"] == "Late Sync"


def test_set_logic_entries_transitions(seeded):
    seeded.post("/api/agent/events",
                json=[ev(1, "t1"), ev(2, "t2", 4), ev(3, "t1", 8)])
    s = seeded.get("/api/sets").json()
    assert len(s) == 1
    detail = seeded.get(f"/api/sets/{s[0]['id']}").json()
    assert detail["entry_count"] == 3
    assert len(detail["transitions"]) == 2


def test_90s_duplicate_not_in_set(seeded):
    seeded.post("/api/agent/events",
                json=[ev(1, "t1"), ev(2, "t1", 1)])  # 1 min later, same track
    s = seeded.get("/api/sets").json()[0]
    detail = seeded.get(f"/api/sets/{s['id']}").json()
    assert detail["entry_count"] == 1
    # but both recorded in plays -> app_play_count
    assert seeded.get("/api/tracks/t1").json()["app_play_count"] == 2


def test_auto_record_gap_ends_set(seeded):
    seeded.post("/api/agent/events", json=[ev(1, "t1")])
    # next play 45 min later -> old set closed, new auto set starts
    seeded.post("/api/agent/events", json=[ev(2, "t2", 45)])
    sets = seeded.get("/api/sets").json()
    assert len(sets) == 2
    ended = [s for s in sets if s["ended_at"]]
    assert len(ended) == 1


def test_auto_record_off(seeded):
    seeded.put("/api/live/auto-record", json={"auto_record": False})
    seeded.post("/api/agent/events", json=[ev(1, "t1")])
    assert seeded.get("/api/sets").json() == []
    assert seeded.get("/api/live/state").json()["auto_record"] is False


def test_manual_start_stop(seeded):
    r = seeded.post("/api/sets/start", json={"name": "My Set"})
    assert r.status_code == 201
    r = seeded.post("/api/sets/start", json={})
    assert r.status_code == 409
    sid = r.json() if isinstance(r.json(), int) else None
    sets = seeded.get("/api/sets").json()
    sid = sets[0]["id"]
    seeded.post("/api/agent/events", json=[ev(1, "t1")])
    seeded.post(f"/api/sets/{sid}/stop")
    assert seeded.get(f"/api/sets/{sid}").json()["ended_at"] is not None


def test_transition_patch_and_entry_delete(seeded):
    seeded.post("/api/agent/events",
                json=[ev(1, "t1"), ev(2, "t2", 4), ev(3, "t1", 8),
                      ev(4, "t2", 12)])
    sid = seeded.get("/api/sets").json()[0]["id"]
    d = seeded.get(f"/api/sets/{sid}").json()
    tr = d["transitions"][0]
    r = seeded.patch(f"/api/transitions/{tr['id']}",
                     json={"favorite": True, "rating": 5, "comment": "nice"})
    assert r.status_code == 200 and r.json()["rating"] == 5
    r = seeded.patch(f"/api/transitions/{tr['id']}", json={"rating": 9})
    assert r.status_code == 422
    # delete entry 3: its two transitions die, a bridge e2->e4 is created,
    # and the annotated e1->e2 transition is untouched.
    mid = d["entries"][2]
    seeded.delete(f"/api/sets/{sid}/entries/{mid['id']}")
    d2 = seeded.get(f"/api/sets/{sid}").json()
    assert d2["entry_count"] == 3
    assert [e["position"] for e in d2["entries"]] == [1, 2, 3]
    assert len(d2["transitions"]) == 2
    fav = [t for t in d2["transitions"] if t["favorite"]]
    assert len(fav) == 1 and fav[0]["comment"] == "nice"
    bridge = [t for t in d2["transitions"] if not t["favorite"]]
    assert len(bridge) == 1
    assert bridge[0]["from_track_id"] == "t2" and bridge[0]["to_track_id"] == "t2"


def test_import_rb_history(seeded, settings):
    import sqlite3

    conn = sqlite3.connect(settings.db_path)
    conn.executescript("""
      INSERT INTO rb_history_sessions (id, name, date_created, is_folder)
        VALUES ('h-imp', 'HISTORY 2026-09-28', '2026-09-28', 0);
      INSERT INTO rb_history_entries (id, history_id, content_id, track_no, created_at)
        VALUES ('e1','h-imp','t1',1,'2026-09-28 22:00:00'),
               ('e2','h-imp','t2',2,'2026-09-28 22:04:00'),
               ('e3','h-imp','t3',3,'2026-09-28 22:08:00');
    """)
    conn.commit()
    conn.close()
    r = seeded.post("/api/sets/import-rb/h-imp")
    assert r.status_code == 200
    sid = r.json()["set_id"]
    r2 = seeded.post("/api/sets/import-rb/h-imp")
    assert r2.json()["already_imported"] is True
    d = seeded.get(f"/api/sets/{sid}").json()
    assert d["source"] == "rb_import" and d["entry_count"] == 3
    assert len(d["transitions"]) == 2


def test_compatible_and_suggestions(seeded):
    # record a live transition t1 -> t2 so it gets history bonus
    seeded.post("/api/agent/events",
                json=[ev(1, "t1"), ev(2, "t2", 4)])
    comp = seeded.get("/api/tracks/t1/compatible").json()
    ids = [c["track"]["id"] for c in comp]
    assert "t2" in ids
    # t3 (4A, 96bpm) fails the camelot/bpm prefilter entirely
    assert "t3" not in ids
    t2 = [c for c in comp if c["track"]["id"] == "t2"][0]
    kinds = {r["kind"] for r in t2["reasons"]}
    assert "key" in kinds and "transition" in kinds


def test_websockets(seeded, app):
    # unauthenticated browser ws -> 4401 (fresh client; `client`/`agent`/
    # `seeded` all share one cached TestClient which is already logged in)
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    anon = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as ei, anon.websocket_connect("/api/live/ws") as ws:
        ws.receive_text()
    assert ei.value.code == 4401
    # agent ws bad token -> 4401
    with pytest.raises(WebSocketDisconnect) as ei2, anon.websocket_connect(
        "/api/agent/ws", headers={"authorization": "Bearer bad"}
    ) as ws:
        ws.receive_text()
    assert ei2.value.code == 4401

    seeded.post("/api/auth/login", json={"password": PASSWORD})
    with seeded.websocket_connect("/api/live/ws") as browser:
        initial = json.loads(browser.receive_text())
        assert initial["now_playing"] is None
        with seeded.websocket_connect(
            "/api/agent/ws",
            headers={"authorization": "Bearer agent-token-123"},
        ) as agent_ws:
            agent_ws.send_text(json.dumps(
                {"type": "hello", "agent_version": "0.1", "hostname": "booth"}
            ))
            # connect broadcast + hello broadcast both queue states; drain
            # until the hello info is visible before sending the play.
            for _ in range(5):
                s = json.loads(browser.receive_text())
                if s["agent"]["hostname"] == "booth":
                    break
            agent_ws.send_text(json.dumps(
                {"type": "play", "event": ev(10, "t1")}))
            ack = json.loads(agent_ws.receive_text())
            assert ack == {"type": "ack", "history_entry_id": "he-10"}
            state = json.loads(browser.receive_text())
            assert state["now_playing"]["id"] == "t1"
            assert state["agent"]["connected"] is True
            assert state["agent"]["hostname"] == "booth"


def test_agent_set_endpoints(seeded, app):
    H = {"Authorization": "Bearer agent-token-123"}
    # status: nothing active, auto_record on
    r = seeded.get("/api/agent/status", headers=H)
    assert r.status_code == 200
    assert r.json() == {"active_set": None, "auto_record": True}
    # start a manual recording via the agent token
    r = seeded.post("/api/agent/sets/start", headers=H, json={"name": "Booth set"})
    assert r.status_code == 201
    sid = r.json()["id"]
    assert r.json()["name"] == "Booth set"
    assert r.json()["auto"] is False
    # second start -> 409
    r = seeded.post("/api/agent/sets/start", headers=H, json={})
    assert r.status_code == 409
    # status now reports the active set
    r = seeded.get("/api/agent/status", headers=H)
    assert r.json()["active_set"]["id"] == sid
    # stop ends it
    r = seeded.post("/api/agent/sets/stop", headers=H)
    assert r.status_code == 200
    assert r.json()["ended_at"] is not None
    r = seeded.post("/api/agent/sets/stop", headers=H)
    assert r.status_code == 404
    # bad/absent token -> 401 (`seeded` carries a default bearer, so use a
    # fresh client for the unauthenticated case)
    from fastapi.testclient import TestClient

    with TestClient(app) as anon:
        assert anon.post("/api/agent/sets/stop").status_code == 401
        assert (
            anon.get(
                "/api/agent/status", headers={"Authorization": "Bearer nope"}
            ).status_code
            == 401
        )


# -- scoring units ----------------------------------------------------------


def test_key_score():
    from djutil_server.services.suggest import camelot_parse, key_score

    a8 = camelot_parse("8A")
    assert key_score(a8, camelot_parse("8A")) == 1.0
    assert key_score(a8, camelot_parse("9A")) == 0.9   # +1
    assert key_score(a8, camelot_parse("7A")) == 0.9   # -1
    assert key_score(a8, camelot_parse("8B")) == 0.85  # relative
    assert key_score(a8, camelot_parse("10A")) == 0.6  # +2 boost
    assert key_score(a8, camelot_parse("6A")) == 0.0   # -2 not a boost
    assert key_score(camelot_parse("12A"), camelot_parse("1A")) == 0.9  # wrap
    assert key_score(camelot_parse("1A"), camelot_parse("12A")) == 0.9
    assert key_score(a8, camelot_parse("bogus")) == 0.0
    assert camelot_parse("x") is None


def test_bpm_score():
    from djutil_server.services.suggest import bpm_score

    s, _, _ = bpm_score(128.0, 128.0)
    assert s == 1.0
    s, _, _ = bpm_score(128.0, 128.0 * 1.03)
    assert s == pytest.approx(1.0)
    s, _, _ = bpm_score(128.0, 128.0 * 1.055)
    assert 0.4 < s < 0.6
    s, _, _ = bpm_score(128.0, 128.0 * 1.08)
    assert s == 0.0
    # half/double time
    s, _, lbl = bpm_score(128.0, 64.0)
    assert s == 1.0 and "2x" in lbl
    s, _, lbl = bpm_score(64.0, 128.0)
    assert s == 1.0 and "½" in lbl
    assert bpm_score(None, 128.0)[0] == 0.0
    assert bpm_score(128.0, 0.0)[0] == 0.0


def test_invalid_tz_fails_fast(monkeypatch):
    monkeypatch.setenv("DJUTIL_TZ", "Mars/Olympus")
    from djutil_server.config import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="IANA"):
        Settings()


def test_set_name_uses_tz(seeded, app):
    app.state.settings.tz = "Pacific/Auckland"
    r = seeded.post("/api/sets/start", json={})
    assert r.status_code == 201
    # Auckland is UTC+12/+13 — the auto name must not be UTC's
    name = r.json()["name"]
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    expected = datetime.now(UTC).astimezone(ZoneInfo("Pacific/Auckland"))
    assert name == f"Set {expected.strftime('%Y-%m-%d %H:%M')}"


# -- deck/history merge ----------------------------------------------------------


def dev(i, tid="t1", minutes=0, base=None, deck=0, seconds=0):
    played = (base or datetime(2026, 10, 1, 20, 0, tzinfo=UTC)) + timedelta(
        minutes=minutes, seconds=seconds
    )
    return {
        "history_entry_id": f"deck:{i:032x}",
        "history_id": "deck",
        "content_id": tid,
        "played_at": played.isoformat(),
        "detected_at": played.isoformat(),
        "source": "deck",
        "deck": deck,
    }


def _plays(seeded, settings):
    import sqlite3

    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM plays ORDER BY played_at, id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def test_deck_then_history_links(seeded, settings):
    """Deck event first, Rekordbox history row 70 s later -> linked, one
    play row, one set entry."""
    seeded.post("/api/agent/events", json=[dev(1, "t1")])
    h = ev(1, "t1", base=datetime(2026, 10, 1, 20, 1, 10, tzinfo=UTC))
    r = seeded.post("/api/agent/events", json=[h])
    # linked, not inserted
    assert r.json()["ingested"] == 0
    plays = _plays(seeded, settings)
    assert len(plays) == 1
    assert plays[0]["source"] == "deck"
    assert plays[0]["deck"] == 0
    assert plays[0]["rb_history_entry_id"] == "he-1"
    s = seeded.get("/api/sets").json()
    assert len(s) == 1
    assert seeded.get(f"/api/sets/{s[0]['id']}").json()["entry_count"] == 1


def test_deck_replay_second_set_entry(seeded, settings):
    """Same track replayed 10 min later (a history session would miss it)
    -> second deck play + second set entry."""
    seeded.post("/api/agent/events",
                json=[dev(1, "t1"), dev(2, "t1", minutes=10)])
    plays = _plays(seeded, settings)
    assert len(plays) == 2
    assert all(p["source"] == "deck" for p in plays)
    s = seeded.get("/api/sets").json()
    assert seeded.get(f"/api/sets/{s[0]['id']}").json()["entry_count"] == 2


def test_history_20min_after_deck_new_play(seeded, settings):
    """History outside the merge window stays its own play."""
    seeded.post("/api/agent/events", json=[dev(1, "t1")])
    h = ev(1, "t1", base=datetime(2026, 10, 1, 20, 20, 0, tzinfo=UTC))
    seeded.post("/api/agent/events", json=[h])
    plays = _plays(seeded, settings)
    assert len(plays) == 2
    assert {p["source"] for p in plays} == {"deck", "history"}


def test_deck_after_history_no_new_set_entry(seeded, settings):
    """History ingested first; a late deck event links to it without a
    second set entry."""
    seeded.post("/api/agent/events", json=[ev(1, "t1")])
    r = seeded.post("/api/agent/events",
                    json=[dev(1, "t1", seconds=30, deck=1)])
    assert r.json()["ingested"] == 1
    plays = _plays(seeded, settings)
    assert len(plays) == 2
    deck_play = [p for p in plays if p["source"] == "deck"][0]
    assert deck_play["rb_history_entry_id"] == "he-1"
    s = seeded.get("/api/sets").json()
    assert seeded.get(f"/api/sets/{s[0]['id']}").json()["entry_count"] == 1


def test_linked_shadow_not_double_counted(seeded, settings):
    """A deck shadow play linked to a history play doesn't double-count in
    app_play_count or the live-state session fallback."""
    # auto_record off first: no set is created, so the live-state session
    # falls back to the raw plays table where the shadow would show.
    seeded.put("/api/live/auto-record", json={"auto_record": False})
    seeded.post("/api/agent/events", json=[ev(1, "t1")])
    seeded.post("/api/agent/events", json=[dev(1, "t1", seconds=30, deck=1)])
    assert len(_plays(seeded, settings)) == 2  # history + shadow deck play
    assert seeded.get("/api/tracks/t1").json()["app_play_count"] == 1
    st = seeded.get("/api/live/state").json()
    assert [s["track"]["id"] for s in st["session"]] == ["t1"]


def test_history_dup_after_link_noop(seeded, settings):
    """A history event already linked onto a deck play is a no-op."""
    seeded.post("/api/agent/events", json=[dev(1, "t1")])
    h = ev(1, "t1", base=datetime(2026, 10, 1, 20, 1, 0, tzinfo=UTC))
    seeded.post("/api/agent/events", json=[h])
    r = seeded.post("/api/agent/events", json=[h])  # same row again
    assert r.json()["ingested"] == 0
    assert len(_plays(seeded, settings)) == 1


def test_history_source_column(seeded, settings):
    seeded.post("/api/agent/events", json=[ev(1, "t1")])
    plays = _plays(seeded, settings)
    assert plays[0]["source"] == "history"
    assert plays[0]["deck"] is None


def test_migration_0002_to_0003_preserves_data(tmp_path):
    """A database already at 0002 upgrades cleanly; plays keep their rows."""
    from alembic import command
    from alembic.config import Config
    from djutil_server.db import ALEMBIC_DIR, make_engine
    from sqlalchemy import text

    engine = make_engine(tmp_path / "mig.db")
    cfg = Config()
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    cfg.attributes["engine"] = engine

    command.upgrade(cfg, "0002_live_sets")
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO plays (history_entry_id, track_id, history_id,"
                " played_at, detected_at, set_id) VALUES"
                " ('he-old', 't1', 'h1', '2026-01-01 20:00:00',"
                "  '2026-01-01 20:00:00', NULL)"
            )
        )
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT source, deck, rb_history_entry_id FROM plays"
                " WHERE history_entry_id = 'he-old'"
            )
        ).first()
        assert row is not None
        assert row[0] == "history" and row[1] is None and row[2] is None
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(plays)"))}
        assert {"source", "deck", "rb_history_entry_id"} <= cols
