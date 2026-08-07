"""Environment-driven configuration.

Mirrors the .env-based configuration style of dreeve-garmin-connector, but
swaps Garmin username/password for Hammerhead OAuth2 client credentials and
a persisted refresh token (Hammerhead has no password-grant flow -- auth
happens once via the /oauth/authorize + /oauth/token dance, see auth.py).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _optional(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    # OAuth2 app credentials, issued by Hammerhead when you register an API client.
    client_id: str
    client_secret: str

    # Where the connector writes downloaded FIT files. Dreeve watches this folder.
    watch_folder: Path

    # Where the sync cursor (which activities are already downloaded) is persisted.
    state_dir: Path

    # Where OAuth tokens are persisted. Kept separate from state_dir so the two can
    # be mounted (and backed up / permissioned) independently on the host.
    token_dir: Path

    # How often to poll for new activities, in seconds.
    poll_interval_seconds: int

    # Base API URLs (overridable for testing against a sandbox/mock).
    api_base_url: str
    auth_base_url: str

    @property
    def token_path(self) -> Path:
        return self.token_dir / "tokens.json"

    @property
    def sync_state_path(self) -> Path:
        return self.state_dir / "sync_state.json"

    @classmethod
    def from_env(cls) -> "Settings":
        watch_folder = Path(_optional("DREEVE_WATCH_FOLDER", "/data/dreeve/watch"))
        state_dir = Path(_optional("HAMMERHEAD_STATE_DIR", "/data/hammerhead/state"))
        token_dir = Path(_optional("HAMMERHEAD_TOKEN_DIR", "/data/hammerhead/tokens"))
        watch_folder.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)
        token_dir.mkdir(parents=True, exist_ok=True)

        return cls(
            client_id=_require("HAMMERHEAD_CLIENT_ID"),
            client_secret=_require("HAMMERHEAD_CLIENT_SECRET"),
            watch_folder=watch_folder,
            state_dir=state_dir,
            token_dir=token_dir,
            poll_interval_seconds=int(_optional("POLL_INTERVAL_SECONDS", "1800")),
            api_base_url=_optional("HAMMERHEAD_API_BASE_URL", "https://api.hammerhead.io/v1/api"),
            auth_base_url=_optional("HAMMERHEAD_AUTH_BASE_URL", "https://api.hammerhead.io/v1/auth"),
        )
