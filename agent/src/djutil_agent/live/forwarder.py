"""Forward live play events over WS with an SQLite outbox + REST fallback."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
from datetime import UTC
from pathlib import Path
from urllib.parse import urlparse

import websockets
from websockets.asyncio.client import ClientConnection

from djutil_shared import PlayEvent

from .. import __version__
from ..rekordbox.watcher import HistoryWatcher
from .outbox import Outbox

logger = logging.getLogger(__name__)

_WS_FAIL_REST_THRESHOLD = 3
_MAX_BACKOFF = 30.0
_HEARTBEAT_IDLE = 15.0  # send a heartbeat after this many idle seconds


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
        deck_watcher: object | None = None,
        play_log: Path | None = None,
    ) -> None:
        self.watcher = watcher
        self.outbox = outbox
        self.server_url = server_url
        self.token = token
        self.rb_version = rb_version
        self.status = status
        self.deck_watcher = deck_watcher
        self.play_log = play_log
        self._ws_failures = 0
        self._stop = asyncio.Event()
        self._new = asyncio.Event()  # set when the outbox gains an event
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

    async def _flush(self, ws: ClientConnection) -> None:
        """Send pending outbox events in order, awaiting each matching ack.

        Acks are read inline here — nothing else may recv on this socket
        while a flush is running.
        """
        for event in self.outbox.pending():
            await ws.send(
                json.dumps({"type": "play", "event": json.loads(event.model_dump_json())})
            )
            try:
                while True:
                    reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                    if (
                        reply.get("type") == "ack"
                        and reply.get("history_entry_id") == event.history_entry_id
                    ):
                        self.outbox.ack(event.history_entry_id)
                        break
                    # non-ack message (e.g. server push): skip it
            except TimeoutError:
                logger.warning("ack timeout for %s", event.history_entry_id)
                raise ConnectionError("ack timeout") from None

    async def _connected(self, ws: ClientConnection) -> None:
        """Post-connect phase: hello, flush, then idle/heartbeat/send loop."""
        await ws.send(await self._hello())
        await self._flush(ws)
        while not self._stop.is_set():
            new_task = asyncio.create_task(self._new.wait())
            stop_task = asyncio.create_task(self._stop.wait())
            done, pending = await asyncio.wait(
                {new_task, stop_task},
                timeout=_HEARTBEAT_IDLE,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            if stop_task in done:
                break
            if not done:  # idle timeout
                await ws.send(json.dumps({"type": "heartbeat"}))
                continue
            self._new.clear()
            await self._flush(ws)

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
                    self._ws_failures = 0
                    backoff = 1.0
                    await self._connected(ws)
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

    _CSV_HEADER = (
        "detected_at", "played_at", "latency_s", "history_entry_id",
        "history_id", "content_id", "artist", "title",
    )

    def _log_plays(self, events: list[PlayEvent]) -> None:
        """Mirror `djutil-agent watch`: append events to play_events.csv."""
        import csv

        if self.play_log is None or not events:
            return
        try:
            new_file = not self.play_log.exists()
            with self.play_log.open("a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if new_file:
                    w.writerow(self._CSV_HEADER)
                for ev in events:
                    t = ev.track
                    latency = (
                        (ev.detected_at - ev.played_at).total_seconds()
                        if ev.played_at
                        else None
                    )
                    w.writerow(
                        [
                            ev.detected_at.isoformat(),
                            (
                                ev.played_at.astimezone(UTC).isoformat()
                                if ev.played_at
                                else ""
                            ),
                            f"{latency:.3f}" if latency is not None else "",
                            ev.history_entry_id,
                            ev.history_id,
                            ev.content_id,
                            t.artist if t else "",
                            t.title if t else "",
                        ]
                    )
        except OSError:
            logger.exception("play event log write failed")

    def _enqueue(self, events: list[PlayEvent]) -> None:
        for event in events:
            self.outbox.put(event)
            self._new.set()  # wake the connected loop to flush
            if self.status is not None:
                t = event.track
                label = (
                    f"{t.artist} - {t.title}"
                    if t is not None
                    else event.content_id
                )
                self.status.set_last_play(label)  # type: ignore[attr-defined]
        self._log_plays(events)

    async def _poll_loop(self) -> None:
        while not self._stop.is_set():
            self._enqueue(self.watcher.poll())
            await asyncio.sleep(1.0)

    async def _deck_loop(self) -> None:
        assert self.deck_watcher is not None
        while not self._stop.is_set():
            try:
                events = await asyncio.to_thread(
                    self.deck_watcher.poll  # type: ignore[attr-defined]
                )
            except Exception:
                logger.exception("deck watcher poll failed")
                events = []
            if self.status is not None:
                self.status.set_deck_reader(  # type: ignore[attr-defined]
                    self.deck_watcher.state  # type: ignore[attr-defined]
                )
            self._enqueue(events)
            await asyncio.sleep(0.2)

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.watcher.prime()
        loops = [self._poll_loop(), self._ws_loop()]
        if self.deck_watcher is not None:
            loops.append(self._deck_loop())
        await asyncio.gather(*loops)

    def stop(self) -> None:
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._stop.set)
        else:
            self._stop.set()
