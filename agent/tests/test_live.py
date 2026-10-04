"""Agent live forwarder/outbox tests."""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import uvicorn

from djutil_agent.live.forwarder import LiveForwarder
from djutil_agent.live.outbox import Outbox
from djutil_shared import PlayEvent


def ev(i: int) -> PlayEvent:
    return PlayEvent(
        history_entry_id=f"he-{i}",
        history_id="h1",
        content_id=f"t-{i}",
        played_at=datetime(2026, 1, 1, 20, i, tzinfo=UTC),
        detected_at=datetime(2026, 1, 1, 20, i, tzinfo=UTC),
    )


class FakeWatcher:
    """HistoryWatcher stand-in: primed once, replays queued events."""

    def __init__(self, events: list[PlayEvent] | None = None) -> None:
        self.events = list(events or [])

    def prime(self) -> None:
        pass

    def poll(self) -> list[PlayEvent]:
        out, self.events = self.events, []
        return out


def make_forwarder(
    tmp_path: Path,
    events: list[PlayEvent] | None = None,
    server: str = "http://x",
    token: str = "e2e-token",
) -> LiveForwarder:
    return LiveForwarder(
        FakeWatcher(events),  # type: ignore[arg-type]
        Outbox(tmp_path / "outbox.db"),
        server,
        token,
        rb_version="7.0",
    )


def test_outbox_persists_and_acks(tmp_path):
    ob = Outbox(tmp_path / "o.db")
    ob.put(ev(1))
    ob.put(ev(2))
    ob2 = Outbox(tmp_path / "o.db")  # reopen == restart
    assert [e.history_entry_id for e in ob2.pending()] == ["he-1", "he-2"]
    ob2.ack("he-1")
    assert [e.history_entry_id for e in ob2.pending()] == ["he-2"]
    # re-put is idempotent
    ob2.put(ev(2))
    assert [e.history_entry_id for e in ob2.pending()] == ["he-2"]


def test_rest_fallback_after_ws_failures(tmp_path, monkeypatch):
    """3 WS failures -> flush pending through POST /api/agent/events."""
    f = make_forwarder(tmp_path, [ev(1), ev(2)])
    f.outbox.put(ev(1))
    f.outbox.put(ev(2))
    posted: list[list[dict[str, object]]] = []

    class FakeResp:
        def raise_for_status(self) -> None:
            pass

    class FakeClient:
        def __init__(self, **kw: object) -> None:
            pass

        async def __aenter__(self) -> FakeClient:
            return self

        async def __aexit__(self, *a: object) -> None:
            pass

        async def post(
            self,
            url: str,
            json: list[dict[str, object]] | None = None,
            **kw: object,
        ) -> FakeResp:
            assert url == "/api/agent/events"
            assert json is not None
            posted.append(json)
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    async def go():
        await f._flush_rest()
        assert f.outbox.pending() == []

    asyncio.run(go())
    assert [e["history_entry_id"] for e in posted[0]] == ["he-1", "he-2"]


class FakeWS:
    """Minimal async WS double for _send_pending_ws."""

    def __init__(self):
        self.sent: list[str] = []
        self._acks: asyncio.Queue[str] = asyncio.Queue()

    async def send(self, msg: str) -> None:
        self.sent.append(msg)
        m = json.loads(msg)
        if m.get("type") == "play":
            self._acks.put_nowait(
                json.dumps(
                    {"type": "ack", "history_entry_id": m["event"]["history_entry_id"]}
                )
            )

    async def recv(self) -> str:
        return await self._acks.get()


def test_resend_unacked_in_order(tmp_path):
    f = make_forwarder(tmp_path)
    f.outbox.put(ev(1))
    f.outbox.put(ev(2))
    ws = FakeWS()
    asyncio.run(f._flush(ws))  # type: ignore[arg-type]
    types = [json.loads(m)["type"] for m in ws.sent]
    assert types == ["play", "play"]
    assert f.outbox.pending() == []  # all acked


def test_flush_skips_non_ack_messages(tmp_path):
    """While awaiting a matching ack, other server messages are ignored."""
    f = make_forwarder(tmp_path)
    f.outbox.put(ev(1))
    ws = FakeWS()

    orig_send = ws.send

    async def send(msg: str) -> None:
        # interleave a non-ack message BEFORE the real ack
        ws._acks.put_nowait(json.dumps({"type": "pong"}))
        await orig_send(msg)

    ws.send = send  # type: ignore[method-assign]
    asyncio.run(f._flush(ws))  # type: ignore[arg-type]
    assert f.outbox.pending() == []


def test_heartbeat_on_idle(tmp_path, monkeypatch):
    """The connected loop sends a heartbeat after the idle timeout."""
    import djutil_agent.live.forwarder as fwd

    monkeypatch.setattr(fwd, "_HEARTBEAT_IDLE", 0.05)
    f = make_forwarder(tmp_path)
    ws = FakeWS()

    async def go():
        task = asyncio.create_task(f._connected(ws))  # type: ignore[arg-type]
        await asyncio.sleep(0.3)
        f.stop()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(task, timeout=5)

    asyncio.run(go())
    types = [json.loads(m)["type"] for m in ws.sent]
    assert types[0] == "hello"
    assert "heartbeat" in types


# -- end-to-end: real uvicorn + real ws -----------------------------------


@pytest.fixture()
def live_server(tmp_path):
    import os

    os.environ.update(
        {
            "DJUTIL_DATA_DIR": str(tmp_path / "data"),
            "DJUTIL_ADMIN_PASSWORD_HASH": "$argon2id$v=19$m=65536,t=3,p=4$"
            "7xOc5GiEnwzvA8c23+YvtQ$Zk+R2q3yKwLelIfTebFTeBKdR4e3gkr6eFdMgielr2M",
            "DJUTIL_AGENT_TOKEN": "e2e-token",
            "DJUTIL_SESSION_SECRET": "x",
            "DJUTIL_COOKIE_SECURE": "false",
        }
    )
    from djutil_server.config import get_settings

    get_settings.cache_clear()
    from djutil_server.app import create_app

    app = create_app(get_settings())
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def test_forwarder_end_to_end(tmp_path, live_server):
    """WS connect -> hello -> play -> server acks and deletes outbox row."""
    f = make_forwarder(tmp_path, server=live_server, events=[ev(1)])

    async def go():
        task = asyncio.create_task(f.run())
        await asyncio.sleep(3)
        f.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    asyncio.run(asyncio.wait_for(go(), timeout=15))
    assert f.outbox.pending() == []
    # and the server recorded the play
    r = httpx.post(
        f"{live_server}/api/auth/login", json={"password": "e2epw"}
    )
    assert r.status_code == 200
    s = httpx.get(f"{live_server}/api/live/state", cookies=r.cookies).json()
    # event carried no track payload, so the summary is None — but the play
    # itself must be recorded in the session.
    assert len(s["session"]) == 1
    assert s["session"][0]["played_at"]
    assert s["agent"]["connected"] is True or s["agent"]["hostname"]


class DelayedWatcher:
    """Returns events only after `delay` seconds — i.e. after the WS is up."""

    def __init__(self, delay: float, events: list[PlayEvent]) -> None:
        self.delay = delay
        self.events = events
        self._t0 = time.monotonic()

    def prime(self) -> None:
        pass

    def poll(self) -> list[PlayEvent]:
        if time.monotonic() - self._t0 < self.delay:
            return []
        out, self.events = self.events, []
        return out


def test_forwarder_delivers_event_arriving_after_connect(tmp_path, live_server):
    """Regression: an event landing in the outbox while the WS is already
    connected must still be sent (previously only flushed on reconnect)."""
    watcher = DelayedWatcher(delay=2.0, events=[ev(1)])
    f = LiveForwarder(
        watcher,  # type: ignore[arg-type]
        Outbox(tmp_path / "outbox.db"),
        live_server,
        "e2e-token",
        rb_version="7.0",
    )

    async def go():
        task = asyncio.create_task(f.run())
        # 2 s watcher delay + poll cadence + ws round trip must fit in 8 s
        await asyncio.sleep(8)
        f.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    asyncio.run(asyncio.wait_for(go(), timeout=15))
    assert f.outbox.pending() == []  # event was sent and acked

    r = httpx.post(f"{live_server}/api/auth/login", json={"password": "e2epw"})
    s = httpx.get(f"{live_server}/api/live/state", cookies=r.cookies).json()
    assert len(s["session"]) == 1


def test_forwarder_delivers_second_event_without_reconnect(tmp_path, live_server):
    """A second play later still goes out over the same connection."""
    watcher = DelayedWatcher(delay=2.0, events=[ev(1)])
    f = LiveForwarder(
        watcher,  # type: ignore[arg-type]
        Outbox(tmp_path / "outbox.db"),
        live_server,
        "e2e-token",
        rb_version="7.0",
    )

    async def go():
        task = asyncio.create_task(f.run())
        await asyncio.sleep(6)
        assert f.outbox.pending() == []  # first event already flushed
        f.outbox.put(ev(2))
        f._new.set()
        await asyncio.sleep(3)
        f.stop()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    asyncio.run(asyncio.wait_for(go(), timeout=15))
    assert f.outbox.pending() == []

    r = httpx.post(f"{live_server}/api/auth/login", json={"password": "e2epw"})
    s = httpx.get(f"{live_server}/api/live/state", cookies=r.cookies).json()
    assert len(s["session"]) == 2
