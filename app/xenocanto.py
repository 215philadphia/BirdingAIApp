"""xeno-canto: reference recordings so users can compare what they heard.

Uses one API key for the whole app (XENOCANTO_API_KEY); users never need their own.
API docs: https://xeno-canto.org/explore/api (version 3).
Each recording has its own Creative Commons licence, which is shown next to it.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://xeno-canto.org/api/3"
CACHE_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class Recording:
    id: str
    audio_url: str
    page_url: str
    recordist: str
    country: str
    location: str
    sound_type: str  # "song", "call", ...
    quality: str  # A (best) to E
    licence_url: str


def _https(url: str) -> str:
    """xeno-canto returns some links without a scheme, like //xeno-canto.org/123."""
    return f"https:{url}" if url.startswith("//") else url


class XenoCantoClient:
    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=15)
        self._cache: dict[str, tuple[float, list[Recording]]] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def recordings(self, scientific_name: str, limit: int = 3) -> list[Recording] | None:
        """Best-quality recordings of a species, or None if unavailable."""
        if not self.enabled:
            return None
        parts = scientific_name.split()
        if len(parts) < 2:
            return []
        cached = self._cache.get(scientific_name)
        if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
            return cached[1][:limit]

        query = f"gen:{parts[0]} sp:{parts[1]} q:A"
        try:
            resp = self._client.get(
                "/recordings", params={"query": query, "key": self.api_key, "per_page": 50}
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("xeno-canto lookup failed for %s: %s", scientific_name, exc)
            return None

        found = [
            Recording(
                id=str(r.get("id", "")),
                audio_url=_https(r.get("file", "")),
                page_url=_https(r.get("url", "")),
                recordist=r.get("rec", ""),
                country=r.get("cnt", ""),
                location=r.get("loc", ""),
                sound_type=r.get("type", ""),
                quality=r.get("q", ""),
                licence_url=_https(r.get("lic", "")),
            )
            for r in data.get("recordings", [])
            if r.get("file")
        ]
        self._cache[scientific_name] = (time.monotonic(), found)
        return found[:limit]
