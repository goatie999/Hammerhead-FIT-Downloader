"""Thin client over the Hammerhead API's Activities endpoints.

This is the direct replacement for whatever module in dreeve-garmin-connector
talked to Garmin Connect (typically `client.get_activities()` /
`client.download_activity(activity_id)` in the various unofficial Garmin
libraries). The endpoints and payload shapes below are taken from the
Hammerhead OpenAPI spec:

    GET  /activities                  -> paginated ActivitySummary list
    GET  /activities/{activityId}     -> full Activity
    GET  /activities/{activityId}/file -> FIT binary (application/vnd.ant.fit)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Iterator, Optional

import httpx

from .auth import HammerheadAuth
from .config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ActivitySummary:
    id: str
    name: str
    created_at: str
    duration: float
    distance: float

    @classmethod
    def from_json(cls, data: dict) -> "ActivitySummary":
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            created_at=data["createdAt"],
            duration=data.get("duration", 0),
            distance=data.get("distance", 0),
        )


class HammerheadClient:
    def __init__(self, settings: Settings, auth: HammerheadAuth, http_client: httpx.Client | None = None):
        self.settings = settings
        self.auth = auth
        self._http = http_client or httpx.Client(timeout=60.0)

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.auth.get_access_token()}"}

    def iter_activities(
        self,
        start_date: Optional[date] = None,
        per_page: int = 50,
    ) -> Iterator[ActivitySummary]:
        """Yields activity summaries newest-first-per-page, walking every
        page returned by GET /activities. `start_date` maps directly to the
        API's `startDate` filter so we don't have to page through activities
        we've already synced."""
        page = 1
        while True:
            params = {"page": page, "perPage": per_page}
            if start_date is not None:
                params["startDate"] = start_date.isoformat()

            response = self._http.get(
                f"{self.settings.api_base_url}/activities",
                params=params,
                headers=self._headers(),
            )
            response.raise_for_status()
            payload = response.json()

            for item in payload.get("data", []):
                yield ActivitySummary.from_json(item)

            total_pages = payload.get("totalPages", 1)
            if page >= total_pages:
                break
            page += 1

    def download_activity_fit(self, activity_id: str) -> bytes:
        """Downloads the raw FIT file for a single activity."""
        response = self._http.get(
            f"{self.settings.api_base_url}/activities/{activity_id}/file",
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.content
