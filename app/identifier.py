"""Bird identification with the BirdNET model.

BirdNET (Cornell Lab of Ornithology & Chemnitz University of Technology) is a
neural network trained on bird recordings from xeno-canto, the Macaulay
Library and other collections. It needs no API key: the model files are
downloaded once and then run locally.

Two BirdNET models are used:
  * the acoustic model, which scores every 3-second chunk of audio against
    about 6,500 species, and
  * the geo model, which predicts which species occur at a latitude/longitude
    in a given week of the year. Restricting the acoustic model to that list
    removes most impossible answers (e.g. a tropical species in Canada).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

MODEL_VERSION = "2.4"

# Besides ~6,500 species (mostly birds, plus some frogs, insects and mammals),
# BirdNET 2.4 has classes for common non-animal sounds. They are reported
# separately so the user knows why a recording found no birds.
NOISE_LABELS = frozenset(
    {
        "Dog",
        "Engine",
        "Environmental",
        "Fireworks",
        "Gun",
        "Human non-vocal",
        "Human vocal",
        "Human whistle",
        "Noise",
        "Power tools",
        "Siren",
    }
)


@dataclass(frozen=True)
class Detection:
    """One species found in a recording."""

    scientific_name: str
    common_name: str
    confidence: float  # best score across all chunks, 0..1
    start_s: float  # start of the chunk with the best score
    end_s: float
    n_segments: int  # how many 3-second chunks the species was heard in

    @property
    def is_noise(self) -> bool:
        return self.scientific_name in NOISE_LABELS


class Identifier(Protocol):
    def identify(
        self,
        audio_path: Path,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        on_date: date | None = None,
    ) -> list[Detection]: ...


def birdnet_week(day: date) -> int:
    """BirdNET splits the year into 48 'weeks': four per month."""
    return (day.month - 1) * 4 + min(4, (day.day - 1) // 7 + 1)


def split_label(label: str) -> tuple[str, str]:
    """BirdNET labels look like 'Turdus migratorius_American Robin'."""
    scientific, _, common = label.partition("_")
    return scientific, common or scientific


def aggregate(
    rows: list[tuple[str, float, float, float]], min_confidence: float
) -> list[Detection]:
    """Collapse per-chunk scores (label, confidence, start, end) to one row per species."""
    best: dict[str, Detection] = {}
    for label, confidence, start_s, end_s in rows:
        if confidence < min_confidence:
            continue
        scientific, common = split_label(label)
        prev = best.get(scientific)
        n = (prev.n_segments if prev else 0) + 1
        if prev is None or confidence > prev.confidence:
            best[scientific] = Detection(
                scientific, common, round(float(confidence), 4), float(start_s), float(end_s), n
            )
        else:
            best[scientific] = Detection(
                prev.scientific_name,
                prev.common_name,
                prev.confidence,
                prev.start_s,
                prev.end_s,
                n,
            )
    return sorted(best.values(), key=lambda d: d.confidence, reverse=True)


class BirdNetIdentifier:
    """Runs BirdNET locally. Models are loaded on first use and then reused."""

    def __init__(self, min_confidence: float = 0.25, geo_threshold: float = 0.03) -> None:
        self.min_confidence = min_confidence
        self.geo_threshold = geo_threshold
        self._lock = threading.Lock()
        self._acoustic = None
        self._geo = None
        self._species_cache: dict[tuple[float, float, int], set[str]] = {}

    def _load(self):
        import birdnet  # imported lazily: it is large and slow to import

        with self._lock:
            if self._acoustic is None:
                log.info("Loading BirdNET %s models (downloaded on first run)", MODEL_VERSION)
                self._acoustic = birdnet.load("acoustic", MODEL_VERSION, "tf", library="litert")
                self._geo = birdnet.load("geo", MODEL_VERSION, "tf", library="litert")
        return self._acoustic, self._geo

    def warm_up(self) -> None:
        self._load()

    def local_species(self, latitude: float, longitude: float, on_date: date) -> set[str]:
        """Labels of species BirdNET expects at this place and time of year."""
        _, geo = self._load()
        key = (round(latitude, 1), round(longitude, 1), birdnet_week(on_date))
        if key not in self._species_cache:
            result = geo.predict(
                latitude, longitude, week=key[2], min_confidence=self.geo_threshold
            )
            self._species_cache[key] = result.to_set()
        return self._species_cache[key]

    def identify(
        self,
        audio_path: Path,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        on_date: date | None = None,
    ) -> list[Detection]:
        acoustic, _ = self._load()
        species_list = None
        if latitude is not None and longitude is not None:
            species_list = self.local_species(latitude, longitude, on_date or date.today())

        result = acoustic.predict(
            str(audio_path),
            top_k=5,
            n_workers=1,
            default_confidence_threshold=self.min_confidence,
            custom_species_list=species_list,
        )
        table = result.to_structured_array()
        rows = [
            (str(r["species_name"]), float(r["confidence"]), float(r["start_time"]), float(r["end_time"]))
            for r in table
        ]
        return aggregate(rows, self.min_confidence)
