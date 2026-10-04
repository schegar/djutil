from conftest import PASSWORD, TOKEN, batch, sample_track


def test_health_public(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_login_and_me(client):
    assert client.get("/api/auth/me").json() == {"authenticated": False}
    r = client.post("/api/auth/login", json={"password": "wrong"})
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"password": PASSWORD})
    assert r.status_code == 200
    assert client.get("/api/auth/me").json() == {"authenticated": True}
    r = client.post("/api/auth/logout")
    assert r.json() == {"authenticated": False}
    assert client.get("/api/auth/me").json() == {"authenticated": False}


def test_rate_limit(client):
    for _ in range(5):
        client.post("/api/auth/login", json={"password": "bad"})
    r = client.post("/api/auth/login", json={"password": PASSWORD})
    assert r.status_code == 429


def test_user_cookie_required(client):
    assert client.get("/api/tracks").status_code == 401
    assert client.get("/api/facets").status_code == 401


def test_agent_token(client):
    assert client.get("/api/sync/state").status_code == 401
    r = client.get(
        "/api/sync/state", headers={"Authorization": "Bearer wrong"}
    )
    assert r.status_code == 401
    r = client.get(
        "/api/sync/state", headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert r.status_code == 200
    assert set(r.json()["entities"]) == {
        "tracks", "cues", "my_tags", "track_my_tags", "playlists",
        "playlist_entries", "history_sessions", "history_entries",
    }


def test_batch_upsert_and_update(agent):
    r = agent.post("/api/sync/batch", json=batch("tracks", [sample_track("t1")], max_usn=10))
    assert r.json() == {"entity": "tracks", "upserted": 1, "deleted": 0}
    # re-upsert updates the row
    agent.post(
        "/api/sync/batch",
        json=batch("tracks", [sample_track("t1", title="New Title", bpm=140.0)], max_usn=20),
    )
    state = agent.get("/api/sync/state").json()["entities"]
    assert state["tracks"] == 20


def test_soft_delete_track_hard_delete_cue(agent):
    agent.post("/api/sync/batch", json=batch(
        "tracks", [sample_track("t1")], max_usn=1))
    agent.post("/api/sync/batch", json=batch(
        "cues", [{"id": "c1", "content_id": "t1", "kind": 0, "in_ms": 100}], max_usn=2))
    agent.post("/api/sync/batch", json=batch("tracks", [], deletes=["t1"], max_usn=3))
    agent.post("/api/sync/batch", json=batch("cues", [], deletes=["c1"]))
    agent.post("/api/auth/login", json={"password": PASSWORD})
    # track soft-deleted: hidden by default, visible with include_deleted
    assert agent.get("/api/tracks").json()["total"] == 0
    assert agent.get("/api/tracks?include_deleted=true").json()["total"] == 1
    # cue hard-deleted: detail has none
    assert agent.get("/api/tracks/t1").json()["cues"] == []


def test_sync_state_usn_monotonic(agent):
    agent.post("/api/sync/batch", json=batch("cues", [], max_usn=50))
    agent.post("/api/sync/batch", json=batch("cues", [], max_usn=10))
    assert agent.get("/api/sync/state").json()["entities"]["cues"] == 50


def test_sync_ids_prunes(agent):
    agent.post("/api/sync/batch", json=batch(
        "playlists", [{"id": "p1", "name": "A"}, {"id": "p2", "name": "B"}]))
    r = agent.post("/api/sync/ids", json={"entity": "playlists", "ids": ["p1"]})
    assert r.json()["deleted"] == 1
    agent.post("/api/auth/login", json={"password": PASSWORD})
    pls = agent.get("/api/facets").json()["playlists"]
    assert [p["id"] for p in pls] == ["p1"]


def test_track_restore(agent):
    agent.post("/api/sync/batch", json=batch(
        "tracks", [sample_track("t1")], max_usn=1))
    agent.post("/api/sync/batch", json=batch(
        "tracks", [], deletes=["t1"], max_usn=2))
    agent.post("/api/auth/login", json={"password": PASSWORD})
    assert agent.get("/api/tracks").json()["total"] == 0
    # track comes back live (deleted=False) -> visible again
    agent.post("/api/sync/batch", json=batch(
        "tracks", [sample_track("t1", deleted=False)], max_usn=3))
    assert agent.get("/api/tracks").json()["total"] == 1


def test_fts_survives_vacuum(agent, settings):
    import sqlite3

    agent.post("/api/sync/batch", json=batch(
        "tracks", [sample_track("t1", title="Stroboscopic Fungi")]))
    agent.post("/api/auth/login", json={"password": PASSWORD})
    assert agent.get("/api/tracks?q=stroboscopic").json()["total"] == 1
    conn = sqlite3.connect(settings.db_path)
    conn.execute("VACUUM")
    conn.close()
    r = agent.get("/api/tracks?q=stroboscopic")
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["id"] == "t1"


def test_artwork_roundtrip(agent, user):
    data = b"\x89PNG fake image bytes"
    import hashlib

    sha = hashlib.sha256(data).hexdigest()
    assert agent.head(f"/api/artwork/{sha}").status_code == 404
    r = agent.put(f"/api/artwork/{sha}", content=data)
    assert r.status_code == 201
    assert agent.head(f"/api/artwork/{sha}").status_code == 200
    r = user.get(f"/api/artwork/{sha}")
    assert r.status_code == 200
    assert r.content == data
    # hash mismatch rejected
    bad = hashlib.sha256(b"other").hexdigest()
    assert agent.put(f"/api/artwork/{bad}", content=data).status_code == 400
    assert agent.head("/api/artwork/notahash").status_code == 400
