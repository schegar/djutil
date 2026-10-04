"""Forward live play events over WS with an SQLite outbox + REST fallback."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
from urllib.parse import urlparse

import websockets
from websockets.asyncio.client import ClientConnection

from .. import __version__
from ..rekordbox.watcher import HistoryWatcher
from .outbox import Outbox

logger = logging.getLogger(__name__)

_WS_FAIL_REST_THRESHOLD = 3
_MAX_BACKOFF = 30.0


def _ws_url(server_url: str) -> str:
    scheme = "wss" if urlparse(server_url).scheme == "https" else "ws"
    host = urlparse(server_url).netloc or server_url.split("://")[-1]
    return f"{scheme}://{host}/api/agent/ws"


class LiveForwarder:
    def __init__(
        self,
        watcher: HistoryWatcher,
        outbox: Outbox,
        server_url: str,
        token: str,
        rb_version: str | None = None,
        status: object | None = None,
    ) -> None:
        self.watcher = watcher
        self.outbox = outbox
        self.server_url = server_url
        self.token = token
        self.rb_version = rb_version
        self.status = status
        self._ws_failures = 0
        self._stop = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    async def _hello(self) -> str:
        return json.dumps(
            {
                "type": "hello",
                "agent_version": __version__,
                "rb_version": self.rb_version,
                "hostname": socket.gethostname(),
            }
        )

    async def _send_pending_ws(self, ws: ClientConnection) -> None:
        await ws.send(await self._hello())
        for event in self.outbox.pending():
            await ws.send(
                json.dumps({"type": "play", "event": json.loads(event.model_dump_json())})
            )
            try:
                reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
            except TimeoutError:
                logger.warning("ack timeout for %s", event.history_entry_id)
                raise ConnectionError("ack timeout") from None
            if (
                reply.get("type") == "ack"
                and reply.get("history_entry_id") == event.history_entry_id
            ):
                self.outbox.ack(event.history_entry_id)

    async def _flush_rest(self) -> None:
        import httpx

        pending = self.outbox.pending()
        if not pending:
            return
        async with httpx.AsyncClient(
            base_url=self.server_url, timeout=15,
            headers={"Authorization": f"Bearer {self.token}"},
        ) as client:
            r = await client.post(
                "/api/agent/events",
                json=[json.loads(e.model_dump_json()) for e in pending],
            )
            r.raise_for_status()
            for e in pending:
                self.outbox.ack(e.history_entry_id)

    def _set_conn(self, state: str) -> None:
        if self.status is not None:
            self.status.set_connection(state)  # type: ignore[attr-defined]

    async def _ws_loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            self._set_conn("connecting")
            try:
                async with websockets.connect(
                    _ws_url(self.server_url),
                    additional_headers={"Authorization": f"Bearer {self.token}"},
                    ping_interval=20,
                ) as ws:
                    self._set_conn("connected")
                    await self._send_pending_ws(ws)
                    self._ws_failures = 0
                    backoff = 1.0
                    # stay connected; poll for new plays is handled by caller
                    async for _raw in ws:
                        pass
            except Exception as exc:
                self._set_conn("disconnected")
                self._ws_failures += 1
                logger.warning("live ws failed (%s); retrying in %.0fs", exc, backoff)
                if self._ws_failures >= _WS_FAIL_REST_THRESHOLD:
                    try:
                        await self._flush_rest()
                    except Exception as rest_exc:
                        logger.warning("REST fallback failed: %s", rest_exc)
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF)

    async def _poll_loop(self) -> None:
        while not self._stop.is_set():
            for event in self.watcher.poll():
                self.outbox.put(event)
                if self.status is not None:
                    t = event.track
                    label = (
                        f"{t.artist} - {t.title}"
                        if t is not None
                        else event.content_id
                    )
                    self.status.set_last_play(label)  # type: ignore[attr-defined]
            await asyncio.sleep(1.0)

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.watcher.prime()
        await asyncio.gather(self._poll_loop(), self._ws_loop())

    def stop(self) -> None:
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._stop.set)
        else:
            self._stop.set()
