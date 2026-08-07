from pathlib import Path

from hammerhead_fit_downloader.client import ActivitySummary
from hammerhead_fit_downloader.state import SyncState
from hammerhead_fit_downloader.sync import _safe_filename, sync_once


class FakeClient:
    def __init__(self, activities, fit_bytes=b"FIT-DATA"):
        self._activities = activities
        self._fit_bytes = fit_bytes
        self.downloaded_ids = []

    def iter_activities(self, start_date=None):
        yield from self._activities

    def download_activity_fit(self, activity_id):
        self.downloaded_ids.append(activity_id)
        return self._fit_bytes


def make_activity(id_="1000.activity.abcd", name="My Epic Ride", created_at="2025-01-25T12:10:09.409Z"):
    return ActivitySummary(id=id_, name=name, created_at=created_at, duration=76765, distance=123.45)


def test_safe_filename_strips_unsafe_characters():
    activity = make_activity(name="Rain / Gravel Loop!!")
    filename = _safe_filename(activity)
    assert filename.startswith("2025-01-25_Rain")
    assert "/" not in filename
    assert filename.endswith(".fit")


def test_sync_once_writes_new_activity_and_skips_synced(tmp_path: Path):
    watch_folder = tmp_path / "watch"
    watch_folder.mkdir()
    state = SyncState.load(tmp_path / "state.json")

    activity = make_activity()
    client = FakeClient([activity])

    written = sync_once(client, state, watch_folder)
    assert written == 1
    files = list(watch_folder.glob("*.fit"))
    assert len(files) == 1
    assert files[0].read_bytes() == b"FIT-DATA"
    assert state.already_synced(activity.id)

    # Second pass with the same activity should not re-download.
    written_again = sync_once(client, state, watch_folder)
    assert written_again == 0
    assert client.downloaded_ids == [activity.id]
