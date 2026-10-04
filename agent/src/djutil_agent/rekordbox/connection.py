"""Open the Rekordbox master.db strictly read-only via SQLCipher.

The engine is constructed the same way pyrekordbox does it internally
(``sqlite+pysqlcipher://`` over ``sqlcipher3``), but without going through
pyrekordbox's config discovery, which asserts when ``options.json`` is stale.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine

ENV_KEY = "DJUTIL_RB_KEY"


class RekordboxKeyError(RuntimeError):
    """Raised when the SQLCipher key for master.db cannot be obtained."""


_KEY_HELP = (
    "The Rekordbox database key could not be obtained or did not work.\n"
    "Rekordbox >= 6.6.5 may need a per-installation key.\n"
    "Fixes, in order:\n"
    f"  1. Pass --key / set {ENV_KEY} to a valid SQLCipher key.\n"
    "  2. Run:  python -m pyrekordbox download-key  (pyrekordbox >= 0.5)\n"
    "  3. Or export the library via Rekordbox XML as a fallback."
)


def _default_key() -> str | None:
    """The well-known key embedded in pyrekordbox (works on most installs)."""
    try:
        from pyrekordbox.db6.database import BLOB
        from pyrekordbox.utils import deobfuscate

        return str(deobfuscate(BLOB))
    except Exception:
        return None


def make_read_only(engine: Engine) -> Engine:
    """Set ``PRAGMA query_only = ON`` on every new connection (defense in depth)."""

    @event.listens_for(engine, "connect")
    def _set_query_only(dbapi_conn: object, _record: object) -> None:
        cursor = dbapi_conn.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA query_only = ON")
        cursor.close()

    return engine


def open_rekordbox(db_path: str | Path, key: str | None = None) -> Engine:
    """Open ``master.db`` and return a SQLAlchemy :class:`Engine`.

    Only used for SELECT statements; nothing is ever committed or flushed.
    """
    key = key or os.environ.get(ENV_KEY) or _default_key()
    if not key:
        raise RekordboxKeyError(_KEY_HELP + "\nNo key available.")

    try:
        from sqlalchemy import create_engine
        from sqlcipher3 import dbapi2 as sqlcipher_dbapi
    except ImportError as exc:
        raise RekordboxKeyError(
            f"{_KEY_HELP}\n'sqlcipher3' package is not installed: {exc}"
        ) from exc

    url = f"sqlite+pysqlcipher://:{key}@/{db_path}?"
    engine = create_engine(url, module=sqlcipher_dbapi)
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT count(*) FROM djmdContent")
    except Exception as exc:
        engine.dispose()
        raise RekordboxKeyError(f"{_KEY_HELP}\nOriginal error: {exc}") from exc

    return make_read_only(engine)
