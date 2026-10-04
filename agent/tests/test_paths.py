import json
from pathlib import Path

import pytest

from djutil_agent.platform.paths import (
    agent_data_dir,
    find_master_db,
    parse_options_json,
    rekordbox_dirs,
)

NEW_FORMAT = json.dumps(
    {"options": [["master-db-path", "C:\\\\RB\\\\master.db", "extra"], ["k", "v"]]}
)
OLD_FORMAT = json.dumps(
    {"options": [["master-db-path", "/Users/x/Library/Pioneer/rekordbox/master.db"]]}
)


def test_parse_options_json_new():
    assert parse_options_json(NEW_FORMAT) == "C:\\\\RB\\\\master.db"


def test_parse_options_json_old():
    parsed = parse_options_json(OLD_FORMAT)
    assert parsed is not None and parsed.endswith("master.db")


@pytest.mark.parametrize("bad", ["", "garbage", "{}", "[]", '{"options": []}', '{"options": 1}'])
def test_parse_options_json_garbage(bad):
    assert parse_options_json(bad) is None


def test_rekordbox_dirs_windows():
    dirs = rekordbox_dirs("win32", home=Path("H"), appdata="C:\\\\AppData")
    assert dirs.options_json == Path(
        "C:\\\\AppData/Pioneer/rekordboxAgent/storage/options.json"
    )
    assert dirs.share_dir == Path("C:\\\\AppData/Pioneer/rekordbox/share")


def test_rekordbox_dirs_macos():
    dirs = rekordbox_dirs("darwin", home=Path("/Users/u"))
    assert dirs.options_json.as_posix().endswith(
        "Library/Application Support/Pioneer/rekordboxAgent/storage/options.json"
    )
    assert dirs.share_dir.as_posix().endswith("Library/Pioneer/rekordbox/share")


def test_rekordbox_dirs_windows_no_appdata():
    with pytest.raises(FileNotFoundError):
        rekordbox_dirs("win32", home=Path("H"), appdata="")


def test_find_master_db_override():
    path, src = find_master_db("/x/master.db")
    assert path == Path("/x/master.db")
    assert src == "cli"


def test_find_master_db_env(monkeypatch):
    monkeypatch.setenv("DJUTIL_RB_DB", "/env/master.db")
    path, src = find_master_db()
    assert path == Path("/env/master.db")
    assert src == "env:DJUTIL_RB_DB"


def test_find_master_db_options_fallback(monkeypatch, tmp_path):
    monkeypatch.delenv("DJUTIL_RB_DB", raising=False)
    monkeypatch.setattr(
        "djutil_agent.platform.paths._pyrekordbox_db_path", lambda: None
    )
    home = tmp_path / "home"
    db = tmp_path / "rb" / "master.db"
    db.parent.mkdir(parents=True)
    db.touch()
    options = (
        home
        / "Library"
        / "Application Support"
        / "Pioneer"
        / "rekordboxAgent"
        / "storage"
        / "options.json"
    )
    options.parent.mkdir(parents=True)
    options.write_text(
        json.dumps({"options": [["db-path", str(db)]]})
    )
    path, src = find_master_db(platform="darwin", home=home)
    assert src == "options.json"
    assert path == db


def test_find_master_db_default_location(monkeypatch, tmp_path):
    monkeypatch.delenv("DJUTIL_RB_DB", raising=False)
    monkeypatch.setattr(
        "djutil_agent.platform.paths._pyrekordbox_db_path", lambda: None
    )
    home = tmp_path / "home"
    db = home / "Library" / "Pioneer" / "rekordbox" / "master.db"
    db.parent.mkdir(parents=True)
    db.touch()
    path, src = find_master_db(platform="darwin", home=home)
    assert src == "default-location"
    assert path == db


def test_find_master_db_not_found(monkeypatch, tmp_path):
    monkeypatch.delenv("DJUTIL_RB_DB", raising=False)
    monkeypatch.setattr(
        "djutil_agent.platform.paths._pyrekordbox_db_path", lambda: None
    )
    with pytest.raises(FileNotFoundError):
        find_master_db(platform="darwin", home=tmp_path / "nohome")


def test_agent_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))  # windows
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    d = agent_data_dir()
    assert d.exists()
