"""Web server: upload or record a bird call, get back the species.

Run with:  uvicorn app.main:app --env-file .env
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .database import Database
from .ebird import EBirdClient
from .identifier import BirdNetIdentifier, Identifier
from .xenocanto import XenoCantoClient

log = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".webm", ".mp4"}


def _readable(path: Path) -> bool:
    import soundfile

    try:
        soundfile.info(str(path))
        return True
    except Exception:  # noqa: BLE001 - soundfile raises several types for unknown formats
        return False


def _to_wav(src: Path) -> Path | None:
    """Convert formats libsndfile can't read (m4a, webm, ...) using ffmpeg, if installed."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    dst = src.with_suffix(".wav")
    proc = subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", "48000", str(dst)],
        capture_output=True,
        timeout=120,
    )
    if proc.returncode != 0:
        return None
    src.unlink(missing_ok=True)
    return dst


def create_app(
    settings: Settings | None = None,
    identifier: Identifier | None = None,
    ebird: EBirdClient | None = None,
    xenocanto: XenoCantoClient | None = None,
) -> FastAPI:
    settings = settings or Settings()
    identifier = identifier or BirdNetIdentifier(min_confidence=settings.min_confidence)
    ebird = ebird or EBirdClient(settings.ebird_api_key)
    xenocanto = xenocanto or XenoCantoClient(settings.xenocanto_api_key)
    db = Database(settings.database_path)
    settings.audio_dir.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # Load the model in the background so the first identification is fast.
        warm_up = getattr(identifier, "warm_up", None)
        if warm_up:
            threading.Thread(target=warm_up, daemon=True).start()
        yield
        db.close()

    app = FastAPI(title="BirdingAIApp", lifespan=lifespan)

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return {
            "model": "BirdNET 2.4",
            "ebird_enabled": ebird.enabled,
            "xenocanto_enabled": xenocanto.enabled,
        }

    @app.post("/api/identify")
    def identify(
        audio: Annotated[UploadFile, File()],
        latitude: Annotated[float | None, Form(ge=-90, le=90)] = None,
        longitude: Annotated[float | None, Form(ge=-180, le=180)] = None,
        recorded_on: Annotated[date | None, Form()] = None,
    ) -> dict[str, Any]:
        if (latitude is None) != (longitude is None):
            raise HTTPException(422, "Send both latitude and longitude, or neither.")
        suffix = Path(audio.filename or "").suffix.lower() or ".wav"
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(415, f"Unsupported file type {suffix!r}.")

        recording_id = db.add_recording(
            recorded_on=recorded_on.isoformat() if recorded_on else None,
            latitude=latitude,
            longitude=longitude,
            original_filename=audio.filename,
        )
        path = settings.audio_dir / f"{recording_id}{suffix}"
        max_bytes = int(settings.max_upload_mb * 1024 * 1024)
        written = 0
        with path.open("wb") as out:
            while chunk := audio.file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    break
                out.write(chunk)
        if written > max_bytes or written == 0:
            path.unlink(missing_ok=True)
            db.delete_recording(recording_id)
            if written == 0:
                raise HTTPException(400, "The audio file is empty.")
            raise HTTPException(413, f"Audio files are limited to {settings.max_upload_mb:g} MB.")

        if not _readable(path):
            converted = _to_wav(path)
            if converted is None or not _readable(converted):
                path.unlink(missing_ok=True)
                db.delete_recording(recording_id)
                raise HTTPException(
                    415, "Could not read this audio. Try WAV, MP3, FLAC or OGG (or install ffmpeg)."
                )
            path = converted
        db.set_audio_file(recording_id, path.name)

        try:
            found = identifier.identify(
                path, latitude=latitude, longitude=longitude, on_date=recorded_on or date.today()
            )
        except Exception:
            log.exception("Identification failed for recording %s", recording_id)
            raise HTTPException(500, "Identification failed. Check the server log.") from None
        detections = [d for d in found if not d.is_noise]
        other_sounds = [d.common_name for d in found if d.is_noise]

        nearby = None
        if latitude is not None and longitude is not None:
            sightings = ebird.recent_nearby(latitude, longitude)
            if sightings is not None:
                nearby = {d.scientific_name: d.scientific_name in sightings for d in detections}
        db.add_detections(recording_id, detections, nearby)
        result = db.get_recording(recording_id)
        assert result is not None
        result["other_sounds"] = other_sounds
        return result

    @app.get("/api/recordings")
    def list_recordings(limit: int = 50) -> list[dict[str, Any]]:
        return db.list_recordings(limit=max(1, min(limit, 500)))

    @app.get("/api/recordings/{recording_id}")
    def get_recording(recording_id: int) -> dict[str, Any]:
        rec = db.get_recording(recording_id)
        if rec is None:
            raise HTTPException(404, "Recording not found.")
        return rec

    @app.get("/api/recordings/{recording_id}/audio")
    def get_audio(recording_id: int) -> FileResponse:
        name = db.audio_file(recording_id)
        if not name or not (settings.audio_dir / name).is_file():
            raise HTTPException(404, "Audio not found.")
        return FileResponse(settings.audio_dir / name)

    @app.delete("/api/recordings/{recording_id}", status_code=204)
    def delete_recording(recording_id: int) -> None:
        name = db.audio_file(recording_id)
        if not db.delete_recording(recording_id):
            raise HTTPException(404, "Recording not found.")
        if name:
            (settings.audio_dir / name).unlink(missing_ok=True)

    @app.get("/api/life-list")
    def life_list() -> list[dict[str, Any]]:
        return db.life_list()

    @app.get("/api/species/{scientific_name}/recordings")
    def reference_recordings(scientific_name: str) -> dict[str, Any]:
        found = xenocanto.recordings(scientific_name)
        if found is None:
            return {"available": False, "recordings": []}
        return {"available": True, "recordings": [r.__dict__ for r in found]}

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


app = create_app()
