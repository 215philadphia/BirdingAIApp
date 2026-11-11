"""Settings read from environment variables (see .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    ebird_api_key: str = field(default_factory=lambda: os.environ.get("EBIRD_API_KEY", "").strip())
    xenocanto_api_key: str = field(
        default_factory=lambda: os.environ.get("XENOCANTO_API_KEY", "").strip()
    )
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("DATA_DIR", "data")))
    # BirdNET scores below this are not reported.
    min_confidence: float = field(default_factory=lambda: _float("MIN_CONFIDENCE", 0.25))
    max_upload_mb: float = field(default_factory=lambda: _float("MAX_UPLOAD_MB", 25))

    @property
    def database_path(self) -> Path:
        return self.data_dir / "birding.db"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"
