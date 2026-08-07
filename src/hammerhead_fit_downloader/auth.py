"""OAuth2 handling for the Hammerhead API.

Hammerhead uses a standard authorization-code OAuth2 flow (see the
`Authorization` tag in the API spec):

    1. One-time, interactive: send the user to
       {auth_base_url}/oauth/authorize?response_type=code&client_id=...&
       redirect_uri=...&scope=activity:read&state=...
       and capture the `code` sent back to your redirect_uri.
    2. Exchange that code for an access/refresh token pair via
       POST {auth_base_url}/oauth/token.
    3. From then on, the connector runs unattended: it refreshes the access
       token using the stored refresh_token whenever it expires.

This replaces the Garmin connector's session/credential login (Garmin has
no public OAuth API) with Hammerhead's supported, ToS-compliant flow.
"""

from __future__ import annotations

import json
import logging
import time
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .config import Settings

logger = logging.getLogger(__name__)

DEFAULT_SCOPE = "activity:read"
# Refresh a bit before actual expiry to avoid racing a request against expiry.
EXPIRY_SAFETY_MARGIN_SECONDS = 60


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str
    token_type: str
    expires_at: float  # unix timestamp
    user_id: str

    def is_expired(self) -> bool:
        return time.time() >= (self.expires_at - EXPIRY_SAFETY_MARGIN_SECONDS)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TokenSet":
        return cls(**data)

    @classmethod
    def from_token_response(cls, payload: dict) -> "TokenSet":
        return cls(
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
            token_type=payload.get("token_type", "Bearer"),
            expires_at=time.time() + float(payload["expires_in"]),
            user_id=str(payload.get("user_id", "")),
        )


class HammerheadAuth:
    """Manages the OAuth2 lifecycle and persists tokens to disk."""

    def __init__(self, settings: Settings, http_client: httpx.Client | None = None):
        self.settings = settings
        self._http = http_client or httpx.Client(timeout=30.0)
        self._tokens: TokenSet | None = self._load_tokens()

    # -- persistence -----------------------------------------------------

    def _load_tokens(self) -> TokenSet | None:
        path = self.settings.token_path
        if not path.exists():
            return None
        try:
            return TokenSet.from_dict(json.loads(path.read_text()))
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning("Could not parse stored tokens at %s; ignoring", path)
            return None

    def _save_tokens(self, tokens: TokenSet) -> None:
        path = self.settings.token_path
        path.write_text(json.dumps(tokens.to_dict(), indent=2))
        path.chmod(0o600)
        self._tokens = tokens

    # -- one-time interactive setup ---------------------------------------

    def build_authorize_url(self, redirect_uri: str, state: str, scope: str = DEFAULT_SCOPE) -> str:
        params = {
            "response_type": "code",
            "client_id": self.settings.client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
        }
        return f"{self.settings.auth_base_url}/oauth/authorize?{urlencode(params)}"

    def run_interactive_setup(self, redirect_uri: str, scope: str = DEFAULT_SCOPE) -> TokenSet:
        """Opens a browser for the user to authorize this app, then prompts
        for the redirected `code` and exchanges it for tokens. Intended to
        be run once, e.g. `python -m hammerhead_fit_downloader.auth setup`.
        """
        state = str(int(time.time()))
        url = self.build_authorize_url(redirect_uri=redirect_uri, state=state, scope=scope)
        print(f"Open this URL and authorize the app:\n\n  {url}\n")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        code = input("Paste the `code` query param from the redirect URL: ").strip()
        tokens = self.exchange_code(code=code, redirect_uri=redirect_uri)
        self._save_tokens(tokens)
        print(f"Saved tokens to {self.settings.token_path}")
        return tokens

    def exchange_code(self, code: str, redirect_uri: str) -> TokenSet:
        response = self._http.post(
            f"{self.settings.auth_base_url}/oauth/token",
            data={
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        response.raise_for_status()
        return TokenSet.from_token_response(response.json())

    # -- ongoing unattended refresh ----------------------------------------

    def _refresh(self, refresh_token: str) -> TokenSet:
        response = self._http.post(
            f"{self.settings.auth_base_url}/oauth/token",
            data={
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        response.raise_for_status()
        return TokenSet.from_token_response(response.json())

    def get_access_token(self) -> str:
        """Returns a valid access token, refreshing (and persisting the new
        refresh token) if the cached one is expired or missing."""
        if self._tokens is None:
            raise RuntimeError(
                "No stored Hammerhead tokens found. Run the interactive setup "
                "first: `python -m hammerhead_fit_downloader.auth setup`."
            )
        if self._tokens.is_expired():
            logger.info("Access token expired; refreshing")
            refreshed = self._refresh(self._tokens.refresh_token)
            self._save_tokens(refreshed)
        return self._tokens.access_token

    def deauthorize(self) -> None:
        if self._tokens is None:
            return
        self._http.post(
            f"{self.settings.auth_base_url}/oauth/deauthorize",
            data={
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
                "token": self._tokens.access_token,
            },
        )
        self.settings.token_path.unlink(missing_ok=True)
        self._tokens = None
