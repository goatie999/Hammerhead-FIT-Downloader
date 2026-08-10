"""Entrypoint. Two modes:

    python -m hammerhead_fit_downloader setup <redirect_uri>
        One-time interactive OAuth2 authorization against Hammerhead.
        Run this once, then ship the resulting tokens.json (or the whole
        /data/hammerhead/tokens folder) to wherever the connector runs.

    python -m hammerhead_fit_downloader run
        Starts the unattended poll loop that downloads new activities into
        Dreeve's watch folder. This is what docker-entrypoint.sh calls.
"""

from __future__ import annotations

import logging
import sys

from .auth import DEFAULT_SCOPE, HammerheadAuth
from .client import HammerheadClient
from .config import ConfigError, Settings
from .state import SyncState
from .sync import run_forever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        logger.error(str(exc))
        return 1

    if not argv or argv[0] == "run":
        auth = HammerheadAuth(settings)
        client = HammerheadClient(settings, auth)
        state = SyncState.load(settings.sync_state_path)
        logger.info("Watching folder: %s", settings.watch_folder)
        run_forever(
            client=client,
            state=state,
            watch_folder=settings.watch_folder,
            poll_interval_seconds=settings.poll_interval_seconds,
        )
        return 0

    if argv[0] == "setup":
        if len(argv) < 2:
            logger.error("Usage: setup <redirect_uri> [scope]")
            return 1
        redirect_uri = argv[1]
        scope = argv[2] if len(argv) > 2 else DEFAULT_SCOPE
        auth = HammerheadAuth(settings)
        auth.run_interactive_setup(redirect_uri=redirect_uri, scope=scope)
        return 0

    logger.error("Unknown command: %s", argv[0])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
