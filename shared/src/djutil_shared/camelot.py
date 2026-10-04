"""Convert Rekordbox key names to Camelot wheel codes."""

import re

# canonical key name -> camelot code
_TABLE: dict[str, str] = {
    "abm": "1A", "g#m": "1A", "b": "1B",
    "ebm": "2A", "d#m": "2A", "f#": "2B", "gb": "2B",
    "bbm": "3A", "a#m": "3A", "db": "3B", "c#": "3B",
    "fm": "4A", "ab": "4B", "g#": "4B",
    "cm": "5A", "eb": "5B", "d#": "5B",
    "gm": "6A", "bb": "6B", "a#": "6B",
    "dm": "7A", "f": "7B",
    "am": "8A", "c": "8B",
    "em": "9A", "g": "9B",
    "bm": "10A", "d": "10B",
    "f#m": "11A", "gbm": "11A", "a": "11B",
    "c#m": "12A", "dbm": "12A", "e": "12B",
}

_CAMELOT_RE = re.compile(r"^(0?[1-9]|1[0-2])\s*([abAB])$")


def to_camelot(key_name: str | None) -> str | None:
    """Map a key name like ``"Am"`` or ``"F#m"`` to a Camelot code.

    Accepts case/whitespace variations, ``min``/``maj`` suffixes and
    already-Camelot values (``"8A"``, ``"08a"``). Unknown input -> ``None``.
    """
    if key_name is None:
        return None
    s = key_name.strip()
    if not s:
        return None

    m = _CAMELOT_RE.match(s)
    if m:
        return f"{int(m.group(1))}{m.group(2).upper()}"

    s = re.sub(r"[\s_-]+", "", s.lower())
    s = s.replace("minor", "min").replace("major", "maj")
    if s.endswith("min"):
        s = s[:-3] + "m"
    elif s.endswith("maj"):
        s = s[:-3]

    return _TABLE.get(s)
