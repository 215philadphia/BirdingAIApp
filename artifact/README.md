# Birding AI as a claude.ai page

A version of the app that runs entirely in the browser, published as a claude.ai artifact:
https://claude.ai/artifact/1S1gqJsxj9bvctSwzCDFF4

- No server: BirdNET 2.4 runs on the viewer's device through [LiteRT.js](https://www.npmjs.com/package/@litertjs/core) (WebAssembly). The audio never leaves the device.
- Upload a recording (on iPhone: Voice Memos → Save to Files). claude.ai pages can't use the microphone or the device's location here, so recording happens in Voice Memos and the place is chosen from a list (or typed as coordinates).
- Choosing a place runs BirdNET's range model to keep only species expected there in that week.
- Results show a spectrogram of the recording with the best clip for each species marked. Tap a species to hear that part.
- Identifications (not the audio) are saved to each viewer's private space in the artifact's database, or in the browser when that isn't available.

## Rebuild

```sh
# BirdNET models (downloaded by the Python package)
.venv/bin/python -c "import birdnet; birdnet.load('acoustic','2.4','tf',library='litert',precision='fp16'); birdnet.load('geo','2.4','tf',library='litert')"

# LiteRT.js and a bundler
mkdir -p /tmp/lrt && cd /tmp/lrt && npm init -y && npm install @litertjs/core@2.6.0 esbuild@0.25.0 && cd -

.venv/bin/python artifact/build.py /tmp/lrt /tmp/birding-artifact
```

The build is about 78 MB, more than one publish allows (64 MB), so publish it in two steps: the page with `wasm/`, `models/acoustic-*` and `models/labels.txt` first, then `models/geo-*`.

Notes:
- Model files are split into parts under the 15 MB file limit, and named `.wasm` only because the artifact service serves a fixed list of file types. The page downloads them as raw bytes and joins them.
- `tools/fix_batch_dim.py` pins each model's flexible batch size (-1) to 1, which LiteRT.js requires. Outputs are unchanged (checked bit-for-bit).
- The fp16 acoustic model is half the download of the fp32 one. On test clips it chose the same species, with confidences within 0.05.
- BirdNET models are licensed CC BY-NC-SA 4.0: non-commercial use only.
