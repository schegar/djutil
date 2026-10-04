import pytest

from djutil_shared import to_camelot


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("Am", "8A"),
        ("am", "8A"),
        ("A minor", "8A"),
        ("C", "8B"),
        ("Cmaj", "8B"),
        ("C major", "8B"),
        ("F#m", "11A"),
        ("Gbm", "11A"),
        ("F#", "2B"),
        ("Gb", "2B"),
        ("Db", "3B"),
        ("C#", "3B"),
        ("Bb", "6B"),
        ("A#", "6B"),
        ("D#", "5B"),
        ("Eb", "5B"),
        ("Ebm", "2A"),
        ("Bbm", "3A"),
        ("Fm", "4A"),
        ("Ab", "4B"),
        ("Cm", "5A"),
        ("Gm", "6A"),
        ("Dm", "7A"),
        ("F", "7B"),
        ("Em", "9A"),
        ("G", "9B"),
        ("Bm", "10A"),
        ("D", "10B"),
        ("A", "11B"),
        ("C#m", "12A"),
        ("Dbm", "12A"),
        ("E", "12B"),
        ("Abm", "1A"),
        ("G#m", "1A"),
        ("B", "1B"),
    ],
)
def test_table(key, expected):
    assert to_camelot(key) == expected


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("8A", "8A"),
        ("08a", "8A"),
        ("12B", "12B"),
        (" 8a ", "8A"),
        ("5 b", "5B"),
    ],
)
def test_passthrough(key, expected):
    assert to_camelot(key) == expected


@pytest.mark.parametrize("key", [None, "", "   ", "Xyz", "13A", "H", "C##m"])
def test_unknown(key):
    assert to_camelot(key) is None
