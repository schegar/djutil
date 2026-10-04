"""Live agent <-> server protocol messages."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .models import PlayEvent


class Hello(BaseModel):
    type: Literal["hello"] = "hello"
    agent_version: str
    rb_version: str | None = None
    hostname: str


class Heartbeat(BaseModel):
    type: Literal["heartbeat"] = "heartbeat"


class Play(BaseModel):
    type: Literal["play"] = "play"
    event: PlayEvent


class Ack(BaseModel):
    type: Literal["ack"] = "ack"
    history_entry_id: str


AgentMessage = Annotated[Hello | Heartbeat | Play, Field(discriminator="type")]
ServerMessage = Annotated[Ack, Field(discriminator="type")]
