"""Server configuration via environment variables (prefix DJUTIL_)."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DJUTIL_", env_file=".env")

    data_dir: Path = Path("./data")
    admin_password_hash: str = ""
    agent_token: str = ""
    session_secret: str = "dev-secret-change-me"
    cookie_secure: bool = True
    static_dir: Path | None = None
    tz: str = "UTC"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "djutil.db"

    @property
    def artwork_dir(self) -> Path:
        return self.data_dir / "artwork"

    @field_validator("tz")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError:
            raise ValueError(
                f"DJUTIL_TZ={v!r} is not a valid IANA time zone "
                "(e.g. 'UTC', 'Europe/Berlin')"
            ) from None
        return v

    def ensure_dirs(self) -> None:
        # Fail with a clear message instead of a cryptic traceback when the
        # data dir (e.g. a bind-mounted volume) isn't writable.
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.artwork_dir.mkdir(parents=True, exist_ok=True)
            probe = self.data_dir / ".write-test"
            probe.touch()
            probe.unlink()
        except OSError as exc:
            import sys

            sys.exit(
                f"DJUTIL_DATA_DIR {self.data_dir} is not writable: {exc}. "
                "If this is a bind mount, chown it to the container user "
                "(uid 10001): sudo chown -R 10001:10001 data backups"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
