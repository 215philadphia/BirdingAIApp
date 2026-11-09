"""SQLite storage for recordings, detections and the user's life list."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .identifier import Detection

SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id    TEXT NOT NULL DEFAULT '',  -- anonymous id of the phone/browser
    created_at   TEXT NOT NULL,
    recorded_on  TEXT,
    latitude     REAL,
    longitude    REAL,
    original_filename TEXT,
    audio_file   TEXT
);

CREATE TABLE IF NOT EXISTS detections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id    INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    scientific_name TEXT NOT NULL,
    common_name     TEXT NOT NULL,
    confidence      REAL NOT NULL,
    start_s         REAL NOT NULL,
    end_s           REAL NOT NULL,
    n_segments      INTEGER NOT NULL,
    reported_nearby INTEGER  -- 1/0 from eBird, NULL when eBird was not checked
);

CREATE INDEX IF NOT EXISTS idx_recordings_device ON recordings(device_id);
CREATE INDEX IF NOT EXISTS idx_detections_recording ON detections(recording_id);
CREATE INDEX IF NOT EXISTS idx_detections_species ON detections(scientific_name);
"""


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        columns = {r[1] for r in self._conn.execute("PRAGMA table_info(recordings)")}
        if columns and "device_id" not in columns:  # database from before device_id existed
            self._conn.execute(
                "ALTER TABLE recordings ADD COLUMN device_id TEXT NOT NULL DEFAULT ''"
            )
        self._conn.executescript(SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        self._conn.close()

    def add_recording(
        self,
        *,
        device_id: str,
        recorded_on: str | None,
        latitude: float | None,
        longitude: float | None,
        original_filename: str | None,
    ) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO recordings (device_id, created_at, recorded_on, latitude, longitude,"
                " original_filename) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    device_id,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    recorded_on,
                    latitude,
                    longitude,
                    original_filename,
                ),
            )
            return int(cur.lastrowid)

    def set_audio_file(self, recording_id: int, audio_file: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE recordings SET audio_file = ? WHERE id = ?", (audio_file, recording_id)
            )

    def add_detections(
        self, recording_id: int, detections: list[Detection], nearby: dict[str, bool] | None
    ) -> None:
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT INTO detections (recording_id, scientific_name, common_name, confidence,"
                " start_s, end_s, n_segments, reported_nearby) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        recording_id,
                        d.scientific_name,
                        d.common_name,
                        d.confidence,
                        d.start_s,
                        d.end_s,
                        d.n_segments,
                        None if nearby is None else int(nearby.get(d.scientific_name, False)),
                    )
                    for d in detections
                ],
            )

    def get_recording(self, recording_id: int, device_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM recordings WHERE id = ? AND device_id = ?", (recording_id, device_id)
        ).fetchone()
        if row is None:
            return None
        return self._with_detections(dict(row))

    def list_recordings(self, device_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM recordings WHERE device_id = ? ORDER BY id DESC LIMIT ?",
            (device_id, limit),
        ).fetchall()
        return [self._with_detections(dict(r)) for r in rows]

    def _with_detections(self, rec: dict[str, Any]) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT scientific_name, common_name, confidence, start_s, end_s, n_segments,"
            " reported_nearby FROM detections WHERE recording_id = ? ORDER BY confidence DESC",
            (rec["id"],),
        ).fetchall()
        rec["detections"] = [_detection_dict(dict(r)) for r in rows]
        rec["has_audio"] = bool(rec.pop("audio_file", None))
        rec.pop("device_id", None)
        return rec

    def audio_file(self, recording_id: int, device_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT audio_file FROM recordings WHERE id = ? AND device_id = ?",
            (recording_id, device_id),
        ).fetchone()
        return row["audio_file"] if row else None

    def delete_recording(self, recording_id: int, device_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM recordings WHERE id = ? AND device_id = ?", (recording_id, device_id)
            )
            return cur.rowcount > 0

    def life_list(self, device_id: str) -> list[dict[str, Any]]:
        """Every species identified at least once, with when it was first heard."""
        rows = self._conn.execute(
            """
            SELECT d.scientific_name,
                   MAX(d.common_name)  AS common_name,
                   COUNT(DISTINCT d.recording_id) AS times_heard,
                   MAX(d.confidence)   AS best_confidence,
                   MIN(r.created_at)   AS first_heard,
                   MAX(r.created_at)   AS last_heard
            FROM detections d JOIN recordings r ON r.id = d.recording_id
            WHERE r.device_id = ?
            GROUP BY d.scientific_name
            ORDER BY first_heard DESC
            """,
            (device_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def _detection_dict(row: dict[str, Any]) -> dict[str, Any]:
    nearby = row.pop("reported_nearby")
    row["reported_nearby"] = None if nearby is None else bool(nearby)
    return row
