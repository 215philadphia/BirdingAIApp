# BirdingAIApp

Record a bird call (or upload a recording) and the app tells you which bird it is.

- **Identification:** [BirdNET](https://birdnet.cornell.edu/) (Cornell Lab of Ornithology and TU Chemnitz) runs on your own server. It recognises about 6,500 species and needs **no API key**.
- **Location filter:** if the user shares their location, BirdNET's range model limits results to species expected there at that time of year.
- **Nearby sightings (optional):** [eBird](https://ebird.org) marks species reported near the user in the last two weeks.
- **Reference sounds (optional):** [xeno-canto](https://xeno-canto.org) recordings let the user compare what they heard.
- **History and life list:** every recording and identification is saved in a local SQLite database.
- **Works on iPhone:** record with the phone's microphone in Safari and add the app to the home screen. Each phone keeps its own history, with no sign-up.

Users never need their own API keys. The app's server holds one key for each service and makes the calls for everyone.

## Run it

Needs Python 3.11 to 3.13. `ffmpeg` is optional; it lets the app accept `.m4a` and `.webm` uploads.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # or requirements.txt without the test tools
cp .env.example .env        # optionally add your eBird / xeno-canto keys
uvicorn app.main:app --env-file .env
```

Open http://localhost:8000. The first start downloads the BirdNET models (about 120 MB, from zenodo.org) to `~/.local/share/birdnet`.

## Use it on your iPhone

Safari only lets a web page use the microphone over **HTTPS**, so the phone needs an `https://` address for the app. There are two ways to get one.

**Option A: tunnel from your computer (free, about 5 minutes).** The app runs on your computer and a free Cloudflare tunnel gives it a temporary public HTTPS address. It works only while your computer is on, and the address changes each time.

1. Install Python 3.11–3.13 from python.org, and `cloudflared`:
   - Mac: `brew install cloudflared`
   - Windows: `winget install --id Cloudflare.cloudflared`
2. Download this repository (green **Code** button → **Download ZIP**, or `git clone`), then in a terminal inside the folder:

   ```sh
   # Mac / Linux
   python3 -m venv .venv && source .venv/bin/activate
   # Windows (PowerShell)
   py -m venv .venv; .venv\Scripts\Activate.ps1

   pip install -r requirements.txt
   python run_phone.py
   ```

3. It prints an `https://….trycloudflare.com` address and a **QR code**. Point the iPhone Camera at the QR code and tap the link. Press Ctrl+C to stop.

Next time, just activate the environment and run `python run_phone.py` again.

**Option B: host it online (always on).** Deploy the included `Dockerfile` to a host that supports Docker, such as Render, Railway or Fly.io:

- Choose a plan with **at least 1 GB of RAM** (identification peaks at about 350 MB).
- Attach a **persistent disk at `/data`**, or history is lost on every redeploy.
- Set `EBIRD_API_KEY` and `XENOCANTO_API_KEY` in the host's environment settings.

The host provides the HTTPS address. The image downloads the BirdNET models while it builds, so the app starts ready.

**On the iPhone**

1. Open the `https://` address in **Safari** and tap **Start recording**. Allow the microphone when asked, and allow location for more accurate results.
2. To make it look and launch like an app: **Share → Add to Home Screen**.
3. To identify an existing **Voice Memo**: share it from Voice Memos, choose **Save to Files**, then use **Upload a recording**.

Tips:
- The app records with the microphone (the iPhone's built-in mic, or AirPods or an external mic if connected). The speaker only plays back your recordings and reference sounds.
- Keep the screen on while recording. iOS stops the microphone when the phone locks, and the app then identifies whatever it already captured.
- Wind and handling noise hurt accuracy most. Hold the phone still and point it toward the bird.
- Safari and the Home Screen app keep separate history on iOS, so use one of them consistently.

If you put the app on a public address, anyone with the link can use it, and every identification runs on your server. Add a password or rate limit before sharing the link widely.

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

Each browser or phone gets an anonymous ID cookie, and the history, audio and life list endpoints only return that device's own recordings.

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
