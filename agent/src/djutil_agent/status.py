"""Thread-safe agent state shared between the engine and the tray UI."""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class StatusSnapshot:
    """Immutable view of the agent's current state."""

    configured: bool = True
    connection: str = "disconnected"  # disconnected | connecting | connected
    last_sync_at: datetime | None = None
    last_sync_ok: bool = True
    last_error: str | None = None
    last_play: str | None = None
    recording: bool = False
    # "active (7.2.10)" | "no offsets" | "not running" | "off" | None
    deck_reader: str | None = None

    def icon_color(self) -> str:
        """red = error/unconfigured, amber = connecting/retrying, green = ok."""
        if not self.configured or self.last_error:
            return "red"
        if self.connection == "connected" and self.last_sync_ok:
            return "green"
        return "amber"

    def status_line(self) -> str:
        if not self.configured:
            return (
                "Not configured – use Open config or `djutil-agent configure`"
            )
        parts = [f"Live: {self.connection}"]
        if self.last_sync_at is not None:
            local = self.last_sync_at.astimezone()
            ok = "ok" if self.last_sync_ok else "failed"
            parts.append(f"last sync {local:%H:%M} ({ok})")
        else:
            parts.append("no sync yet")
        if self.deck_reader:
            parts.append(f"decks: {self.deck_reader}")
        if self.last_play:
            parts.append(f"last play: {self.last_play}")
        if self.last_error:
            parts.append(f"error: {self.last_error}")
        return " · ".join(parts)


class AgentStatus:
    """Mutable status; engine threads write, the tray reads via snapshot()."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snap = StatusSnapshot()

    def snapshot(self) -> StatusSnapshot:
        with self._lock:
            return self._snap

    def _set(self, **kw: Any) -> None:
        with self._lock:
            self._snap = replace(self._snap, **kw)

    def set_configured(self, configured: bool) -> None:
        self._set(configured=configured)

    def set_connection(self, state: str) -> None:
        assert state in ("disconnected", "connecting", "connected")
        self._set(connection=state)

    def mark_sync(self, ok: bool, error: str | None = None) -> None:
        self._set(
            last_sync_at=datetime.now(UTC),
            last_sync_ok=ok,
            last_error=None if ok else error,
        )

    def set_error(self, message: str | None) -> None:
        self._set(last_error=message)

    def set_last_play(self, label: str | None) -> None:
        self._set(last_play=label)

    def set_deck_reader(self, state: str | None) -> None:
        self._set(deck_reader=state)

    def set_recording(self, recording: bool) -> None:
        self._set(recording=recording)
