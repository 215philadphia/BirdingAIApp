"""eBird: which species people have reported near a location recently.

Uses one API key for the whole app (EBIRD_API_KEY); users never need their own.
API docs: https://documenter.getpostman.com/view/664302/S1ENwy59
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://api.ebird.org/v2"
CACHE_SECONDS = 60 * 60  # sightings for an area change slowly; one lookup per hour is plenty


@dataclass(frozen=True)
class Sighting:
    scientific_name: str
    common_name: str
    last_seen: str  # e.g. "2026-11-08 07:45"
    location: str


class EBirdClient:
    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=10)
        self._cache: dict[tuple[float, float], tuple[float, dict[str, Sighting]]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def recent_nearby(
        self, latitude: float, longitude: float, radius_km: int = 25, days_back: int = 14
    ) -> dict[str, Sighting] | None:
        """Species reported within radius_km in the last days_back days, keyed by
        scientific name. Returns None if eBird is not configured or unreachable;
        identification must keep working without it."""
        if not self.enabled:
            return None
        key = (round(latitude, 2), round(longitude, 2))
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
            return cached[1]
        try:
            resp = self._client.get(
                "/data/obs/geo/recent",
                params={
                    "lat": f"{latitude:.2f}",
                    "lng": f"{longitude:.2f}",
                    "dist": min(radius_km, 50),
                    "back": min(days_back, 30),
                },
                headers={"X-eBirdApiToken": self.api_key},
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("eBird lookup failed: %s", exc)
            return None

        sightings: dict[str, Sighting] = {}
        for obs in data:
            sci = obs.get("sciName")
            if not sci or sci in sightings:  # results are newest first
                continue
            sightings[sci] = Sighting(
                scientific_name=sci,
                common_name=obs.get("comName", sci),
                last_seen=obs.get("obsDt", ""),
                location=obs.get("locName", ""),
            )
        self._cache[key] = (time.monotonic(), sightings)
        return sightings
