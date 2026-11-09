import io
import struct
import wave
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.ebird import EBirdClient
from app.identifier import Detection
from app.main import create_app
from app.xenocanto import XenoCantoClient


def wav_bytes(seconds: float = 1.0, rate: int = 48000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(seconds * rate))
    return buf.getvalue()


class FakeIdentifier:
    def __init__(self):
        self.calls = []

    def identify(self, audio_path, *, latitude=None, longitude=None, on_date=None):
        self.calls.append((Path(audio_path), latitude, longitude, on_date))
        return [
            Detection("Turdus migratorius", "American Robin", 0.91, 3.0, 6.0, 2),
            Detection("Cardinalis cardinalis", "Northern Cardinal", 0.55, 0.0, 3.0, 1),
            Detection("Engine", "Engine", 0.4, 0.0, 3.0, 1),
        ]


def ebird_handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["X-eBirdApiToken"] == "ebird-key"
    assert request.url.path == "/v2/data/obs/geo/recent"
    return httpx.Response(
        200,
        json=[
            {"sciName": "Turdus migratorius", "comName": "American Robin",
             "obsDt": "2026-11-08 07:45", "locName": "Fairmount Park"},
        ],
    )


def xc_handler(request: httpx.Request) -> httpx.Response:
    assert request.url.params["key"] == "xc-key"
    assert request.url.params["query"] == "gen:Turdus sp:migratorius q:A"
    return httpx.Response(
        200,
        json={
            "numRecordings": "1",
            "recordings": [
                {"id": "123", "file": "https://xeno-canto.org/123/download",
                 "url": "//xeno-canto.org/123", "rec": "A. Recordist", "cnt": "United States",
                 "loc": "Philadelphia", "type": "song", "q": "A",
                 "lic": "//creativecommons.org/licenses/by-nc-sa/4.0/"},
            ],
        },
    )


@pytest.fixture
def identifier():
    return FakeIdentifier()


@pytest.fixture
def client(tmp_path, identifier):
    settings = Settings(ebird_api_key="ebird-key", xenocanto_api_key="xc-key", data_dir=tmp_path)
    ebird = EBirdClient(
        "ebird-key",
        httpx.Client(base_url="https://api.ebird.org/v2", transport=httpx.MockTransport(ebird_handler)),
    )
    xc = XenoCantoClient(
        "xc-key",
        httpx.Client(base_url="https://xeno-canto.org/api/3", transport=httpx.MockTransport(xc_handler)),
    )
    app = create_app(settings, identifier=identifier, ebird=ebird, xenocanto=xc)
    with TestClient(app) as c:
        yield c


def upload(client, data=None, name="call.wav", **form):
    return client.post("/api/identify", files={"audio": (name, data or wav_bytes(), "audio/wav")}, data=form)


def test_status(client):
    assert client.get("/api/status").json() == {
        "model": "BirdNET 2.4", "ebird_enabled": True, "xenocanto_enabled": True,
    }


def test_identify_with_location_marks_ebird_sightings(client, identifier):
    resp = upload(client, latitude="39.95", longitude="-75.16", recorded_on="2026-11-09")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    names = [d["common_name"] for d in body["detections"]]
    assert names == ["American Robin", "Northern Cardinal"]
    assert body["detections"][0]["reported_nearby"] is True
    assert body["detections"][1]["reported_nearby"] is False
    assert body["other_sounds"] == ["Engine"]
    assert body["has_audio"] is True
    _, lat, lon, on_date = identifier.calls[0]
    assert (lat, lon, str(on_date)) == (39.95, -75.16, "2026-11-09")


def test_identify_without_location_skips_ebird(client):
    body = upload(client).json()
    assert all(d["reported_nearby"] is None for d in body["detections"])


def test_history_audio_life_list_and_delete(client):
    first = upload(client).json()
    upload(client)
    history = client.get("/api/recordings").json()
    assert [r["id"] for r in history] == [first["id"] + 1, first["id"]]

    audio = client.get(f"/api/recordings/{first['id']}/audio")
    assert audio.status_code == 200 and audio.content[:4] == b"RIFF"

    life = {s["common_name"]: s for s in client.get("/api/life-list").json()}
    assert set(life) == {"American Robin", "Northern Cardinal"}
    assert life["American Robin"]["times_heard"] == 2

    assert client.delete(f"/api/recordings/{first['id']}").status_code == 204
    assert client.get(f"/api/recordings/{first['id']}").status_code == 404
    assert client.get(f"/api/recordings/{first['id']}/audio").status_code == 404


def test_rejects_bad_uploads(client, identifier):
    assert upload(client, name="notes.txt").status_code == 415
    assert upload(client, data=b"not really audio").status_code == 415
    assert upload(client, latitude="39.9").status_code == 422
    assert upload(client, latitude="95", longitude="0").status_code == 422
    assert identifier.calls == []
    assert client.get("/api/recordings").json() == []


def test_rejects_oversized_upload(tmp_path, identifier):
    settings = Settings(data_dir=tmp_path, max_upload_mb=0.01)
    with TestClient(create_app(settings, identifier=identifier)) as c:
        assert upload(c, data=wav_bytes(seconds=1)).status_code == 413


def test_reference_recordings(client):
    body = client.get("/api/species/Turdus migratorius/recordings").json()
    assert body["available"] is True
    rec = body["recordings"][0]
    assert rec["page_url"] == "https://xeno-canto.org/123"
    assert rec["licence_url"].startswith("https://creativecommons.org/")


def test_reference_recordings_without_key(tmp_path, identifier):
    with TestClient(create_app(Settings(data_dir=tmp_path), identifier=identifier)) as c:
        assert c.get("/api/species/Turdus migratorius/recordings").json() == {
            "available": False, "recordings": [],
        }


def test_ebird_failure_does_not_break_identification(tmp_path, identifier):
    broken = EBirdClient(
        "ebird-key",
        httpx.Client(base_url="https://api.ebird.org/v2",
                     transport=httpx.MockTransport(lambda r: httpx.Response(503))),
    )
    with TestClient(create_app(Settings(data_dir=tmp_path), identifier=identifier, ebird=broken)) as c:
        resp = upload(c, latitude="39.95", longitude="-75.16")
        assert resp.status_code == 200
        assert resp.json()["detections"][0]["reported_nearby"] is None


def test_serves_web_page(client):
    resp = client.get("/")
    assert resp.status_code == 200 and "Birding AI" in resp.text


def test_each_device_sees_only_its_own_recordings(client):
    mine = upload(client).json()
    assert client.cookies.get("birding_device")

    client.cookies.clear()  # a different phone
    assert client.get("/api/recordings").json() == []
    assert client.get("/api/life-list").json() == []
    assert client.get(f"/api/recordings/{mine['id']}").status_code == 404
    assert client.get(f"/api/recordings/{mine['id']}/audio").status_code == 404
    assert client.delete(f"/api/recordings/{mine['id']}").status_code == 404


def test_ignores_malformed_device_cookie(client):
    client.cookies.set("birding_device", "../../etc/passwd")
    resp = client.get("/api/recordings")
    assert resp.status_code == 200
    assert len(resp.cookies.get("birding_device", "")) == 32


def test_device_column_added_to_old_database(tmp_path):
    import sqlite3

    from app.database import Database

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE recordings (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, recorded_on TEXT,"
        " latitude REAL, longitude REAL, original_filename TEXT, audio_file TEXT)"
    )
    conn.commit()
    conn.close()
    db = Database(path)
    assert db.add_recording(device_id="a" * 32, recorded_on=None, latitude=None,
                            longitude=None, original_filename=None) == 1
