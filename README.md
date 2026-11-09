# BirdingAIApp

Record a bird call (or upload a recording) and the app tells you which bird it is.

- **Identification:** [BirdNET](https://birdnet.cornell.edu/) (Cornell Lab of Ornithology and TU Chemnitz) runs on your own server. It recognises about 6,500 species and needs **no API key**.
- **Location filter:** if the user shares their location, BirdNET's range model limits results to species expected there at that time of year.
- **Nearby sightings (optional):** [eBird](https://ebird.org) marks species reported near the user in the last two weeks.
- **Reference sounds (optional):** [xeno-canto](https://xeno-canto.org) recordings let the user compare what they heard.
- **History and life list:** every recording and identification is saved in a local SQLite database.

Users never need their own API keys. The app's server holds one key for each service and makes the calls for everyone.

## Run it

Needs Python 3.11 to 3.13. `ffmpeg` is optional; it lets the app accept `.m4a` and `.webm` uploads.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # optionally add your eBird / xeno-canto keys
uvicorn app.main:app --env-file .env
```

Open http://localhost:8000. The first start downloads the BirdNET models (about 120 MB, from zenodo.org) to `~/.local/share/birdnet`.

The browser only allows microphone recording on `localhost` or over HTTPS. To use the recorder from your phone, serve the app over HTTPS, for example through a tunnel such as `cloudflared` or `ngrok`.

### API keys (optional)

| Key | What it adds | Get one |
|---|---|---|
| `EBIRD_API_KEY` | "Reported nearby on eBird" badge | https://ebird.org/api/keygen |
| `XENOCANTO_API_KEY` | "Hear examples" button | Your account page on xeno-canto.org (needs a verified email) |

Keep the keys in `.env` on the server. `.env` is git-ignored; never put keys in the web page or commit them.

## How it works

```
browser ── records audio, converts it to WAV ──► POST /api/identify
                                                   │
                         BirdNET acoustic model ◄──┤  score each 3-second clip
                         BirdNET geo model     ◄──┤  species expected at lat/lon + week
                         eBird (cached 1 h)    ◄──┤  recent sightings nearby
                         SQLite                ◄──┘  save recording + detections
```

| Endpoint | Purpose |
|---|---|
| `POST /api/identify` | Form fields: `audio` (file), optional `latitude`, `longitude`, `recorded_on` (YYYY-MM-DD) |
| `GET /api/recordings` | History, newest first |
| `GET /api/recordings/{id}/audio` | Replay a saved recording |
| `DELETE /api/recordings/{id}` | Delete a recording and its audio |
| `GET /api/life-list` | Every species identified so far |
| `GET /api/species/{scientific name}/recordings` | xeno-canto reference recordings |
| `GET /api/status` | Which optional services are configured |

Code layout: `app/identifier.py` (BirdNET), `app/ebird.py`, `app/xenocanto.py`, `app/database.py`, `app/main.py` (web server), `app/static/` (web page).

## Tests

```sh
pytest
```

The tests use a stand-in for BirdNET and simulated eBird and xeno-canto responses, so they run offline in about a second.

## Licences

- This app's code: add a licence of your choice.
- The BirdNET models are licensed **CC BY-NC-SA 4.0: non-commercial use only**. A paid app needs a licence from the BirdNET team or a different model.
- Each xeno-canto recording has its own Creative Commons licence (many are non-commercial). The app shows a link to each one's licence.
- eBird data is subject to the [eBird API terms of use](https://www.birds.cornell.edu/home/ebird-api-terms-of-use/).
