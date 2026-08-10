"""Sync loop: pulls new activity FIT files from Hammerhead and drops them
into Dreeve's watch folder -- the same end goal as dreeve-garmin-connector,
just sourced from a different provider.

Dreeve watches a folder for new FIT/TCX/GPX files and ingests whatever shows
up, so the only contract we need to honor is: write a complete file, then
rename it into place atomically so Dreeve never sees a half-written file.
Concretely: download to `<name>.part`, and only once the write has finished
does it get renamed to `<name>.fit` -- a rename is atomic on the same
filesystem, so Dreeve either sees no file at all, or the finished one, never
something in between.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from .client import ActivitySummary, HammerheadClient
from .state import SyncState

logger = logging.getLogger(__name__)

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_basename(activity: ActivitySummary) -> str:
    """A filesystem-safe name for this activity, without an extension."""
    name = _UNSAFE_CHARS.sub("-", activity.name.strip()) or "activity"
    return f"{activity.created_at[:10]}_{name}_{activity.id}"


def sync_once(client: HammerheadClient, state: SyncState, watch_folder: Path) -> int:
    """Runs a single sync pass. Returns the number of new files written."""
    written = 0
    for activity in client.iter_activities(start_date=state.start_date()):
        if state.already_synced(activity.id):
            continue

        logger.info("Downloading activity %s (%s)", activity.id, activity.name)
        fit_bytes = client.download_activity_fit(activity.id)

        basename = _safe_basename(activity)
        final_path = watch_folder / f"{basename}.fit"
        tmp_path = watch_folder / f"{basename}.part"
        tmp_path.write_bytes(fit_bytes)
        tmp_path.rename(final_path)  # atomic on the same filesystem

        state.mark_synced(activity.id, activity.created_at)
        state.save()
        written += 1
        logger.info("Wrote %s", final_path)

    if written == 0:
        logger.info("No new activities to sync")
    return written


def run_forever(client: HammerheadClient, state: SyncState, watch_folder: Path, poll_interval_seconds: int) -> None:
    while True:
        try:
            sync_once(client, state, watch_folder)
        except Exception:
            logger.exception("Sync pass failed; will retry next interval")
        time.sleep(poll_interval_seconds)
