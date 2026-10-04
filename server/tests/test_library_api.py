from conftest import batch, sample_track


def seed(agent):
    tracks = [
        sample_track("t1", title="Alpha Storm", artist="DJ One",
                     genre="Techno", bpm=128.0, camelot="8A", rating=5,
                     dj_play_count=10, date_added="2024-01-01"),
        sample_track("t2", title="Beta \"Quote\" (Edit)", artist="DJ Two",
                     genre="House", bpm=124.0, camelot="8B", rating=3,
                     dj_play_count=0, date_added="2024-02-01"),
        sample_track("t3", title="Gamma!", artist="DJ One",
                     genre="Techno", bpm=132.5, camelot="2A", rating=2,
                     dj_play_count=5, date_added="2024-03-01"),
    ]
    agent.post("/api/sync/batch", json=batch("tracks", tracks, max_usn=100))
    agent.post("/api/sync/batch", json=batch(
        "cues", [{"id": "c1", "content_id": "t1", "kind": 0, "in_ms": 500,
                  "comment": "mem"}]))
    agent.post("/api/sync/batch", json=batch(
        "my_tags", [{"id": "mt0", "name": "Root"},
                    {"id": "mt1", "name": "Peak", "parent_id": "mt0"}]))
    agent.post("/api/sync/batch", json=batch(
        "track_my_tags", [{"id": "smt1", "my_tag_id": "mt1",
                           "content_id": "t1", "track_no": 1}]))
    agent.post("/api/sync/batch", json=batch(
        "playlists", [{"id": "pf", "name": "Folder", "is_folder": True},
                      {"id": "p1", "name": "Set A", "parent_id": "pf"}]))
    agent.post("/api/sync/batch", json=batch(
        "playlist_entries", [{"id": "pe1", "playlist_id": "p1",
                              "content_id": "t2", "track_no": 1}]))
    agent.post("/api/sync/batch", json=batch(
        "history_sessions",
        [{"id": "hf", "name": "2024", "is_folder": True},
         {"id": "h1", "name": "S1", "date_created": "2024-05-01"}]))
    agent.post("/api/sync/batch", json=batch(
        "history_entries",
        [{"id": "he1", "history_id": "h1", "content_id": "t1",
          "track_no": 1, "created_at": "2024-05-01T20:00:00"}]))
    agent.post("/api/auth/login", json={"password": "testpw"})


def test_list_and_sort(agent):
    seed(agent)
    r = agent.get("/api/tracks")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert body["items"][0]["title"] == "Alpha Storm"
    assert body["items"][0]["play_count"] == 10

    desc = agent.get("/api/tracks?sort=bpm&order=desc").json()
    assert desc["items"][0]["bpm"] == 132.5


def test_filters(agent):
    seed(agent)
    assert agent.get("/api/tracks?bpm_min=125&bpm_max=130").json()["total"] == 1
    assert agent.get("/api/tracks?genre=Techno").json()["total"] == 2
    assert agent.get("/api/tracks?genre=Techno,House").json()["total"] == 3
    assert agent.get("/api/tracks?camelot=8A").json()["total"] == 1
    assert agent.get("/api/tracks?rating_min=3").json()["total"] == 2
    assert agent.get("/api/tracks?never_played=true").json()["total"] == 1
    assert agent.get("/api/tracks?play_count_min=5").json()["total"] == 2
    assert agent.get("/api/tracks?added_from=2024-02-01").json()["total"] == 2
    assert agent.get("/api/tracks?added_to=2024-01-31").json()["total"] == 1
    assert agent.get("/api/tracks?my_tag=mt1").json()["total"] == 1
    assert agent.get("/api/tracks?playlist=p1").json()["total"] == 1
    assert agent.get("/api/tracks?limit=2").json()["items"].__len__() == 2


def test_fts(agent):
    seed(agent)
    assert agent.get("/api/tracks?q=alpha").json()["total"] == 1
    assert agent.get("/api/tracks?q=alpha stor").json()["total"] == 1
    # punctuation/quotes must not break FTS
    assert agent.get("/api/tracks?q=%22beta%22").json()["total"] == 1
    assert agent.get("/api/tracks?q=gamma!").json()["total"] == 1
    assert agent.get("/api/tracks?q=%22%22%20%20!!!").json()["total"] == 3
    assert agent.get("/api/tracks?q=DJ One").json()["total"] == 2


def test_track_detail(agent):
    seed(agent)
    r = agent.get("/api/tracks/t1")
    assert r.status_code == 200
    d = r.json()
    assert d["title"] == "Alpha Storm"
    assert d["cues"][0]["comment"] == "mem"
    assert d["my_tags"][0]["name"] == "Peak"
    assert d["history"][0]["history_name"] == "S1"
    assert agent.get("/api/tracks/t2").json()["playlists"][0]["id"] == "p1"
    assert agent.get("/api/tracks/nope").status_code == 404


def test_facets(agent):
    seed(agent)
    f = agent.get("/api/facets").json()
    assert {g["name"]: g["count"] for g in f["genres"]} == {
        "Techno": 2, "House": 1}
    assert {c["name"] for c in f["camelots"]} == {"8A", "8B", "2A"}
    assert f["bpm_min"] == 124.0 and f["bpm_max"] == 132.5
    assert f["my_tags"][0]["name"] == "Root"
    assert f["my_tags"][0]["children"][0]["name"] == "Peak"
    assert f["playlists"][0]["name"] == "Folder"
    assert f["playlists"][0]["children"][0]["name"] == "Set A"


def test_history_sessions(agent):
    seed(agent)
    sessions = agent.get("/api/history/sessions").json()
    assert len(sessions) == 1
    assert sessions[0]["name"] == "S1"
    assert sessions[0]["entry_count"] == 1
    detail = agent.get("/api/history/sessions/h1").json()
    assert detail["entries"][0]["track"]["title"] == "Alpha Storm"
    assert agent.get("/api/history/sessions/nope").status_code == 404
