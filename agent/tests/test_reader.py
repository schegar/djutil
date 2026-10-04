from djutil_shared import LibrarySnapshot


def test_counts(reader):
    c = reader.counts()
    assert c["tracks"] == 2  # t3 is deleted
    assert c["artists"] == 4
    assert c["cues"] == 3
    assert c["my_tags"] == 2
    assert c["playlists"] == 3
    assert c["playlist_entries"] == 2
    assert c["history_sessions"] == 3
    assert c["history_entries"] == 3


def test_tracks_mapping(reader):
    tracks = reader.tracks()
    assert {t.id for t in tracks} == {"t1", "t2"}
    t1 = next(t for t in tracks if t.id == "t1")
    assert t1.title == "Song One"
    assert t1.mix == "Radio Edit"
    assert t1.artist == "Artist One"
    assert t1.remixer == "Remixer Two"
    assert t1.composer == "Composer Three"
    assert t1.original_artist == "Org Artist"
    assert t1.album == "Album One"
    assert t1.genre == "Techno"
    assert t1.label == "Label One"
    assert t1.key_name == "Am"
    assert t1.camelot == "8A"
    assert t1.bpm == 128.0  # 12800 / 100
    assert t1.length_s == 300
    assert t1.rating == 4
    assert t1.color == "Red"
    assert t1.comment == "comment1"
    assert t1.dj_play_count == 7
    assert t1.file_path == "/music/"
    assert t1.file_name == "song1.mp3"
    assert t1.file_type == 1
    assert t1.bitrate == 320
    assert t1.sample_rate == 44100
    assert t1.release_year == 2020
    assert t1.release_date == "2020-05-01"
    assert t1.date_added == "2021-01-02"
    assert t1.artwork_path == "art/t1.jpg"
    assert t1.rb_local_usn == 10
    assert t1.updated_at is not None
    assert t1.deleted is False


def test_rating_255_scale(reader):
    t2 = next(t for t in reader.tracks() if t.id == "t2")
    assert t2.rating == 5  # 255 -> 5


def test_deleted_excluded_by_default(reader):
    assert all(not t.deleted for t in reader.tracks())
    assert len(reader.tracks(include_deleted=True)) == 3


def test_track_lookup(reader):
    assert reader.track("t1").title == "Song One"
    assert reader.track("nope") is None


def test_cues(reader):
    cues = reader.cues()
    assert len(cues) == 3
    mem = next(c for c in cues if c.kind == 0)
    assert mem.comment == "memory cue"
    assert mem.in_ms == 0 or mem.in_ms == 500


def test_my_tags(reader):
    tags = reader.my_tags()
    child = next(t for t in tags if t.id == "mt1")
    assert child.parent_id == "mt0"
    links = reader.track_my_tags()
    assert links[0].content_id == "t1"


def test_playlists(reader):
    pls = reader.playlists()
    folder = next(p for p in pls if p.id == "pl0")
    assert folder.is_folder and not folder.is_smart
    smart = next(p for p in pls if p.id == "pl2")
    assert smart.is_smart
    entries = reader.playlist_entries()
    assert [e.track_no for e in entries] == [1, 2]


def test_history(reader):
    sessions = reader.history_sessions()
    assert len(sessions) == 3
    assert next(s for s in sessions if s.id == "h0").is_folder
    entries = reader.history_entries()
    assert [e.id for e in entries] == ["sh1", "sh2", "sh3"]
    since = reader.history_entries(since="2024-01-06 00:00:00")
    assert [e.id for e in since] == ["sh3"]


def test_snapshot_roundtrip(reader, tmp_path):
    snap = reader.snapshot(db_path="/tmp/master.db", rekordbox_version="7.0.1")
    text = snap.model_dump_json()
    loaded = LibrarySnapshot.model_validate_json(text)
    assert loaded == snap
    assert len(loaded.tracks) == 2
    assert loaded.rekordbox_version == "7.0.1"
