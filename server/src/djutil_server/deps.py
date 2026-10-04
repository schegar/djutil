"""Shared FastAPI dependencies."""

from typing import cast

from fastapi import Request
from sqlalchemy.engine import Engine


def get_engine(request: Request) -> Engine:
    return cast(Engine, request.app.state.engine)
