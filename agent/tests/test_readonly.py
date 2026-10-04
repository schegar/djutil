import pytest
import sqlalchemy
from sqlalchemy import text

from djutil_agent.rekordbox.connection import make_read_only


def test_query_only_blocks_writes(engine):
    make_read_only(engine)
    with engine.connect() as conn:
        conn.execute(text("SELECT COUNT(*) FROM djmdContent"))
        with pytest.raises(sqlalchemy.exc.OperationalError):
            conn.execute(
                text("INSERT INTO djmdArtist (ID) VALUES ('x')")
            )
