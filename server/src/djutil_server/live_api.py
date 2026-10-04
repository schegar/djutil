"""Live endpoints: agent WS + REST events, browser WS, live state."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import TypeAdapter
from sqlalchemy import text

from djutil_shared import PlayEvent

from .auth import require_agent, require_user
from .config import Settings
from .schemas import AutoRecordOut, LiveState, SetOut, SetStartRequest
from .services.live import (
    _end_set,
    _start_set,
    active_set,
    auto_record_on,
    close_stale_set,
    ingest_play,
    live_state,
    set_setting,
)

router = APIRouter(prefix="/api", tags=["live"])

_event_adapter = TypeAdapter(PlayEvent)


def _agent_token_ok(settings: Settings, token: str | None) -> bool:
    return bool(settings.agent_token) and token is not None and hmac.compare_digest(
        token, settings.agent_token
    )


def _name_fn(settings: Settings) -> Callable[[datetime], str]:
    from zoneinfo import ZoneInfo

    def name(d: datetime) -> str:
        try:
            local = d.astimezone(ZoneInfo(settings.tz))
        except Exception:
            local = d
        return f"Set {local.strftime('%Y-%m-%d %H:%M')}"

    return name


async def _publish(app: FastAPI) -> None:
    state = live_state(app.state.engine, app.state.hub)
    await app.state.hub.broadcast(LiveState.model_validate(state).model_dump(mode="json"))


@router.websocket("/agent/ws")
async def agent_ws(ws: WebSocket) -> None:
    settings = ws.app.state.settings
    auth = ws.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    await ws.accept()
    if not _agent_token_ok(settings, token):
        await ws.close(code=4401, reason="Invalid agent token")
        return

    hub = ws.app.state.hub
    hub.agent_connected = True
    hub.agent_last_seen = datetime.now(UTC)
    try:
        await _publish(ws.app)
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            hub.agent_last_seen = datetime.now(UTC)
            mtype = msg.get("type")
            if mtype == "hello":
                hub.agent_hostname = msg.get("hostname")
                hub.agent_rb_version = msg.get("rb_version")
                await _publish(ws.app)
            elif mtype == "play":
                event = _event_adapter.validate_python(msg["event"])
                ingest_play(
                    ws.app.state.engine,
                    hub,
                    event,
                    set_name_fn=_name_fn(settings),
                )
                await ws.send_text(
                    json.dumps(
                        {"type": "ack", "history_entry_id": event.history_entry_id}
                    )
                )
                await _publish(ws.app)
            elif mtype == "heartbeat":
                pass
    except WebSocketDisconnect:
        pass
    finally:
        hub.agent_connected = False
        with contextlib.suppress(Exception):
            await _publish(ws.app)


@router.post("/agent/events")
async def agent_events(
    events: list[PlayEvent],
    request: Request,
    _: bool = Depends(require_agent),
) -> dict[str, Any]:
    app = request.app
    name_fn = _name_fn(app.state.settings)
    results = [
        ingest_play(
            app.state.engine, app.state.hub, e, set_name_fn=name_fn
        )
        for e in events
    ]
    await _publish(app)
    return {"ingested": sum(1 for r in results if r["inserted"])}


@router.websocket("/live/ws")
async def live_ws(ws: WebSocket) -> None:
    session = ws.session if hasattr(ws, "session") else {}
    await ws.accept()
    if not session.get("user"):
        await ws.close(code=4401, reason="Authentication required")
        return
    hub = ws.app.state.hub
    hub.sockets.add(ws)
    try:
        state = live_state(ws.app.state.engine, hub)
        await ws.send_text(
            json.dumps(LiveState.model_validate(state).model_dump(mode="json"), default=str)
        )
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.sockets.discard(ws)


@router.post("/agent/sets/start", response_model=SetOut, status_code=201)
async def agent_start_set(
    body: SetStartRequest,
    request: Request,
    _: bool = Depends(require_agent),
) -> SetOut:
    """Agent-token set recording control."""
    settings = request.app.state.settings
    engine = request.app.state.engine
    with engine.begin() as conn:
        if active_set(conn):
            raise HTTPException(409, "A set is already active")
        now = datetime.now(UTC)
        name = body.name or _name_fn(settings)(now)
        sid = _start_set(conn, name, now, auto=False)
        row = dict(
            conn.execute(
                text("SELECT * FROM sets WHERE id = :id"), {"id": sid}
            ).mappings().one()
        )
    await _publish(request.app)
    return SetOut.model_validate(row)


@router.post("/agent/sets/stop", response_model=SetOut)
async def agent_stop_set(
    request: Request, _: bool = Depends(require_agent)
) -> SetOut:
    engine = request.app.state.engine
    with engine.begin() as conn:
        s = active_set(conn)
        if not s:
            raise HTTPException(404, "No active set")
        _end_set(conn, s["id"], datetime.now(UTC))
        s["ended_at"] = datetime.now(UTC)
    await _publish(request.app)
    return SetOut.model_validate(s)


@router.get("/agent/status")
def agent_status(
    request: Request, _: bool = Depends(require_agent)
) -> dict[str, Any]:
    with request.app.state.engine.connect() as conn:
        return {
            "active_set": active_set(conn),
            "auto_record": auto_record_on(conn),
        }


@router.get("/live/state", response_model=LiveState)
def get_live_state(
    request: Request, _: bool = Depends(require_user)
) -> LiveState:
    return LiveState.model_validate(
        live_state(request.app.state.engine, request.app.state.hub)
    )


@router.get("/live/auto-record", response_model=AutoRecordOut)
def get_auto_record(
    request: Request, _: bool = Depends(require_user)
) -> AutoRecordOut:
    from .services.live import auto_record_on

    with request.app.state.engine.connect() as conn:
        return AutoRecordOut(auto_record=auto_record_on(conn))


@router.put("/live/auto-record", response_model=AutoRecordOut)
async def put_auto_record(
    body: AutoRecordOut,
    request: Request,
    _: bool = Depends(require_user),
) -> AutoRecordOut:
    with request.app.state.engine.begin() as conn:
        set_setting(conn, "auto_record", "1" if body.auto_record else "0")
    await _publish(request.app)
    return body


async def stale_set_sweeper(app: FastAPI) -> None:
    """Background task: close stale auto sets every 60 s."""
    while True:
        await asyncio.sleep(60)
        try:
            with app.state.engine.begin() as conn:
                if close_stale_set(conn, datetime.now(UTC)):
                    await _publish(app)
        except Exception:
            pass


@router.get("/agent/ping")
def agent_ping(_: bool = Depends(require_agent)) -> dict[str, Any]:
    return {"ok": True}
