"""Fixture: a plain SQLite DB mimicking the djmd* schema used by the reader."""

import pytest
from sqlalchemy import create_engine, text

DDL = """
CREATE TABLE djmdArtist (ID TEXT PRIMARY KEY, Name TEXT);
CREATE TABLE djmdAlbum (ID TEXT PRIMARY KEY, Name TEXT, AlbumArtistID TEXT);
CREATE TABLE djmdGenre (ID TEXT PRIMARY KEY, Name TEXT);
CREATE TABLE djmdLabel (ID TEXT PRIMARY KEY, Name TEXT);
CREATE TABLE djmdKey (ID TEXT PRIMARY KEY, ScaleName TEXT, Seq INTEGER);
CREATE TABLE djmdColor (ID TEXT PRIMARY KEY, ColorCode INTEGER, SortKey INTEGER, Commnt TEXT);
CREATE TABLE djmdContent (
    ID TEXT PRIMARY KEY,
    FolderPath TEXT, FileNameL TEXT, FileNameS TEXT,
    Title TEXT, ArtistID TEXT, AlbumID TEXT, GenreID TEXT,
    BPM INTEGER, Length INTEGER, TrackNo INTEGER, BitRate INTEGER,
    BitDepth INTEGER, Commnt TEXT, FileType INTEGER, Rating INTEGER,
    ReleaseYear INTEGER, RemixerID TEXT, LabelID TEXT, OrgArtistID TEXT,
    ComposerID TEXT,
    KeyID TEXT, StockDate TEXT, ColorID TEXT, DJPlayCount TEXT,
    ImagePath TEXT, Subtitle TEXT, SampleRate INTEGER,
    ReleaseDate TEXT, DateCreated TEXT,
    rb_local_deleted INTEGER DEFAULT 0, rb_local_usn INTEGER,
    created_at TEXT, updated_at TEXT
);
CREATE TABLE djmdCue (
    ID TEXT PRIMARY KEY, ContentID TEXT, InMsec INTEGER, OutMsec INTEGER,
    Kind INTEGER, Color INTEGER, Comment TEXT,
    rb_local_deleted INTEGER DEFAULT 0, rb_local_usn INTEGER
);
CREATE TABLE djmdMyTag (ID TEXT PRIMARY KEY, Seq INTEGER, Name TEXT,
    Attribute INTEGER, ParentID TEXT,
    rb_local_deleted INTEGER DEFAULT 0, rb_local_usn INTEGER);
CREATE TABLE djmdSongMyTag (ID TEXT PRIMARY KEY, MyTagID TEXT,
    ContentID TEXT, TrackNo INTEGER,
    rb_local_deleted INTEGER DEFAULT 0, rb_local_usn INTEGER);
CREATE TABLE djmdPlaylist (ID TEXT PRIMARY KEY, Seq INTEGER, Name TEXT,
    Attribute INTEGER, ParentID TEXT, SmartList TEXT,
    rb_local_deleted INTEGER DEFAULT 0, rb_local_usn INTEGER);
CREATE TABLE djmdSongPlaylist (ID TEXT PRIMARY KEY, PlaylistID TEXT,
    ContentID TEXT, TrackNo INTEGER,
    rb_local_deleted INTEGER DEFAULT 0, rb_local_usn INTEGER);
CREATE TABLE djmdHistory (ID TEXT PRIMARY KEY, Seq INTEGER, Name TEXT,
    Attribute INTEGER, ParentID TEXT, DateCreated TEXT,
    rb_local_deleted INTEGER DEFAULT 0, rb_local_usn INTEGER);
CREATE TABLE djmdSongHistory (ID TEXT PRIMARY KEY, HistoryID TEXT,
    ContentID TEXT, TrackNo INTEGER, created_at TEXT, updated_at TEXT,
    rb_local_deleted INTEGER DEFAULT 0, rb_local_usn INTEGER);
"""

DATA = """
INSERT INTO djmdArtist VALUES ('a1','Artist One'),('a2','Remixer Two'),
    ('a3','Composer Three'),('a4','Org Artist');
INSERT INTO djmdAlbum VALUES ('al1','Album One','a1');
INSERT INTO djmdGenre VALUES ('g1','Techno');
INSERT INTO djmdLabel VALUES ('l1','Label One');
INSERT INTO djmdKey VALUES ('k1','Am',1),('k2','F#m',2);
INSERT INTO djmdColor VALUES ('c1',1,1,'Red');
INSERT INTO djmdContent (ID, FolderPath, FileNameL, Title, ArtistID, AlbumID,
    GenreID, BPM, Length, BitRate, Commnt, FileType, Rating, ReleaseYear,
    RemixerID, LabelID, OrgArtistID, ComposerID, KeyID, StockDate, ColorID,
    DJPlayCount,
    ImagePath, Subtitle, SampleRate, ReleaseDate, DateCreated,
    rb_local_deleted, rb_local_usn, created_at, updated_at)
VALUES
    ('t1','/music/','song1.mp3','Song One','a1','al1','g1',12800,300,320,
     'comment1',1,4,2020,'a2','l1','a4','a3','k1','2021-01-02','c1','7',
     'art/t1.jpg','Radio Edit',44100,'2020-05-01','2021-01-02',
     0,10,'2021-01-02 10:00:00.000 +00:00','2022-01-01 10:00:00.000 +00:00'),
    ('t2','/music/','song2.flac','Song Two','a1',NULL,'g1',12250,240,1411,
     NULL,5,255,2021,NULL,NULL,NULL,NULL,'k2','2021-03-04',NULL,'0',
     NULL,NULL,NULL,'2021-03-04','2021-03-04',
     0,11,'2021-03-04 10:00:00.000 +00:00','2022-01-01 10:00:00.000 +00:00'),
    ('t3','/music/','gone.mp3','Deleted Song','a1',NULL,NULL,12000,200,320,
     NULL,1,0,NULL,NULL,NULL,NULL,NULL,NULL,'2020-01-01',NULL,'3',
     NULL,NULL,NULL,'2020-01-01','2020-01-01',
     1,12,'2020-01-01 10:00:00.000 +00:00','2022-01-01 10:00:00.000 +00:00');
INSERT INTO djmdCue VALUES
    ('cu1','t1',0,500,0,-1,'memory cue',0,20),
    ('cu2','t1',1500,NULL,1,2,'hot cue A',0,21),
    ('cu3','t1',8000,16000,4,3,'loop',0,22);
INSERT INTO djmdMyTag VALUES
    ('mt0',1,'Root',0,NULL,0,30),('mt1',2,'Peak',0,'mt0',0,31);
INSERT INTO djmdSongMyTag VALUES ('smt1','mt1','t1',1,0,32);
INSERT INTO djmdPlaylist VALUES
    ('pl0',1,'Folder',1,NULL,NULL,0,40),
    ('pl1',2,'My Playlist',0,'pl0',NULL,0,41),
    ('pl2',3,'Smart',4,'pl0','<x/>',0,42);
INSERT INTO djmdSongPlaylist VALUES
    ('sp1','pl1','t1',1,0,43),('sp2','pl1','t2',2,0,44);
INSERT INTO djmdHistory VALUES
    ('h0',1,'2024',1,NULL,'2024-01-01',0,50),
    ('h1',2,'Session 1',0,'h0','2024-01-05',0,51),
    ('h2',3,'Session 2',0,'h0','2024-01-06',0,52);
INSERT INTO djmdSongHistory VALUES
    ('sh1','h1','t1',1,'2024-01-05 20:00:00.000 +00:00',NULL,0,53),
    ('sh2','h1','t2',2,'2024-01-05 20:10:00.000 +00:00',NULL,0,54),
    ('sh3','h2','t1',1,'2024-01-06 21:00:00.000 +00:00',NULL,0,55);
"""


@pytest.fixture()
def db_file(tmp_path):
    path = tmp_path / "master.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        for stmt in DDL.split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
        for stmt in DATA.split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
    engine.dispose()
    return path


@pytest.fixture()
def engine(db_file):
    eng = create_engine(f"sqlite:///{db_file}")
    yield eng
    eng.dispose()


@pytest.fixture()
def reader(engine):
    from djutil_agent.rekordbox.reader import RekordboxReader

    return RekordboxReader(engine)
