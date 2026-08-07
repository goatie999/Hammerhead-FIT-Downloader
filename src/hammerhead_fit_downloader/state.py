"""Tracks which activities have already been synced to Dreeve's watch folder,
so repeated polls don't redownload/rewrite the same FIT files."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Set


@dataclass
class SyncState:
    path: Path
    last_synced_date: str | None = None
    synced_activity_ids: Set[str] = field(default_factory=set)

    @classmethod
    def load(cls, path: Path) -> "SyncState":
        if not path.exists():
            return cls(path=path)
        data = json.loads(path.read_text())
        return cls(
            path=path,
            last_synced_date=data.get("last_synced_date"),
            synced_activity_ids=set(data.get("synced_activity_ids", [])),
        )

    def save(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "last_synced_date": self.last_synced_date,
                    # Cap how many ids we remember so this file doesn't grow forever.
                    "synced_activity_ids": sorted(self.synced_activity_ids)[-2000:],
                },
                indent=2,
            )
        )

    def start_date(self) -> date | None:
        if not self.last_synced_date:
            return None
        return date.fromisoformat(self.last_synced_date)

    def mark_synced(self, activity_id: str, created_at: str) -> None:
        self.synced_activity_ids.add(activity_id)
        synced_date = datetime.fromisoformat(created_at.replace("Z", "+00:00")).date().isoformat()
        if self.last_synced_date is None or synced_date > self.last_synced_date:
            self.last_synced_date = synced_date

    def already_synced(self, activity_id: str) -> bool:
        return activity_id in self.synced_activity_ids
