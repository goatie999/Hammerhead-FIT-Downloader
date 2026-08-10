from pathlib import Path

import pytest

from hammerhead_fit_downloader.client import ActivitySummary
from hammerhead_fit_downloader.state import SyncState
from hammerhead_fit_downloader.sync import _safe_basename, sync_once


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


def test_safe_basename_strips_unsafe_characters():
    activity = make_activity(name="Rain / Gravel Loop!!")
    basename = _safe_basename(activity)
    assert basename.startswith("2025-01-25_Rain")
    assert "/" not in basename
    # No extension in the basename itself -- sync_once appends .part/.fit.
    assert not basename.endswith(".fit")
    assert not basename.endswith(".part")


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
    # No leftover .part files once the download is complete.
    assert list(watch_folder.glob("*.part")) == []

    # Second pass with the same activity should not re-download.
    written_again = sync_once(client, state, watch_folder)
    assert written_again == 0
    assert client.downloaded_ids == [activity.id]


def test_the_final_name_only_appears_once_the_file_is_complete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proves the write-then-rename order: Dreeve must never be able to see
    # the final .fit name before the .part write has fully landed.
    watch_folder = tmp_path / "watch"
    watch_folder.mkdir()
    state = SyncState.load(tmp_path / "state.json")
    activity = make_activity()
    client = FakeClient([activity])

    observed = {}
    real_rename = Path.rename

    def spy(self: Path, target):
        observed["source_name"] = self.name
        observed["source_existed_before_rename"] = self.exists()
        observed["destination_existed_before_rename"] = Path(target).exists()
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", spy)

    sync_once(client, state, watch_folder)

    assert observed["source_name"].endswith(".part")
    assert observed["source_existed_before_rename"] is True
    assert observed["destination_existed_before_rename"] is False
    final_files = list(watch_folder.glob("*.fit"))
    assert len(final_files) == 1
    assert list(watch_folder.glob("*.part")) == []
