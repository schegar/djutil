import pytest
from argon2 import PasswordHasher
from djutil_server.app import create_app
from djutil_server.config import Settings
from fastapi.testclient import TestClient

PASSWORD = "testpw"
TOKEN = "agent-token-123"


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    from djutil_server.auth import _failures

    _failures.clear()
    yield


@pytest.fixture()
def settings(tmp_path):
    return Settings(
        data_dir=tmp_path / "data",
        admin_password_hash=PasswordHasher().hash(PASSWORD),
        agent_token=TOKEN,
        session_secret="test-secret",
        cookie_secure=False,
    )


@pytest.fixture()
def app(settings):
    return create_app(settings)


@pytest.fixture()
def client(app):
    # Must be entered so every request/websocket shares one portal (event
    # loop) — otherwise each websocket_connect gets its own loop and
    # cross-socket broadcasts write into a stream owned by another loop,
    # whose waiters are never woken (the test_websockets hang).
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def agent(client):
    client.headers["Authorization"] = f"Bearer {TOKEN}"
    return client


@pytest.fixture()
def user(client):
    r = client.post("/api/auth/login", json={"password": PASSWORD})
    assert r.status_code == 200
    return client


def sample_track(tid: str, **kw: object) -> dict[str, object]:
    t = {"id": tid, "title": f"Title {tid}", "artist": "DJ X",
         "genre": "Techno", "bpm": 128.0, "camelot": "8A",
         "dj_play_count": 3, "rating": 4, "date_added": "2024-01-01"}
    t.update(kw)
    return t


def batch(entity: str, upserts: list[dict[str, object]], deletes: list[str] | None = None,
          max_usn: int | None = None) -> dict[str, object]:
    return {
        "entity": entity,
        "upserts": upserts,
        "deletes": deletes or [],
        "max_usn": max_usn,
    }
