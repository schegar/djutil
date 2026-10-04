"""Agent configuration (server URL + token), stored in the data dir."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .platform.paths import agent_data_dir

ENV_SERVER = "DJUTIL_SERVER"
ENV_TOKEN = "DJUTIL_AGENT_TOKEN"


@dataclass
class AgentConfig:
    server: str = ""
    token: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.server and self.token)


def config_path() -> Path:
    return agent_data_dir() / "config.json"


def load_config() -> AgentConfig:
    cfg = AgentConfig()
    path = config_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cfg.server = str(data.get("server", ""))
            cfg.token = str(data.get("token", ""))
        except (json.JSONDecodeError, OSError):
            pass
    cfg.server = os.environ.get(ENV_SERVER, cfg.server)
    cfg.token = os.environ.get(ENV_TOKEN, cfg.token)
    return cfg


def save_config(cfg: AgentConfig) -> Path:
    path = config_path()
    path.write_text(
        json.dumps({"server": cfg.server, "token": cfg.token}, indent=2),
        encoding="utf-8",
    )
    if os.name == "posix":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path
