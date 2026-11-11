"use strict";

const $ = (sel) => document.querySelector(sel);
const MAX_SECONDS = 60;

// ---------- tabs ----------
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".view").forEach((v) =>
      v.classList.toggle("active", v.id === `view-${tab.dataset.view}`));
    if (tab.dataset.view === "history") loadHistory();
    if (tab.dataset.view === "lifelist") loadLifeList();
  });
});

// ---------- status ----------
let status = { ebird_enabled: false, xenocanto_enabled: false };
fetch("/api/status").then((r) => r.json()).then((s) => {
  status = s;
  $("#footer-ebird").hidden = !s.ebird_enabled;
  $("#footer-xc").hidden = !s.xenocanto_enabled;
}).catch(() => {});

$("#recorded-on").value = new Date().toLocaleDateString("en-CA"); // YYYY-MM-DD

// ---------- location ----------
let coords = null;
function requestLocation() {
  const out = $("#location-status");
  if (!$("#use-location").checked) { coords = null; out.textContent = ""; return; }
  if (!navigator.geolocation) { out.textContent = "Location isn't available in this browser."; return; }
  out.textContent = "Finding your location…";
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      coords = { lat: pos.coords.latitude, lon: pos.coords.longitude };
      out.textContent = `Using ${coords.lat.toFixed(2)}, ${coords.lon.toFixed(2)}`;
    },
    () => { coords = null; out.textContent = "Location was not shared; checking against all species worldwide."; },
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 },
  );
}
$("#use-location").addEventListener("change", requestLocation);
requestLocation();

// ---------- recording ----------
let recorder = null;
let timerId = null;
let wakeLock = null;

// Keep the screen on while recording: iPhones stop the microphone when the screen locks.
async function keepScreenOn(on) {
  try {
    if (on && "wakeLock" in navigator) wakeLock = await navigator.wakeLock.request("screen");
    if (!on && wakeLock) { await wakeLock.release(); wakeLock = null; }
  } catch { /* not supported or not allowed; recording still works */ }
}

// If the user switches apps or locks the phone mid-recording, identify what was captured.
document.addEventListener("visibilitychange", () => {
  if (document.hidden && recorder && recorder.state === "recording") recorder.stop();
});

$("#record-btn").addEventListener("click", async () => {
  if (recorder && recorder.state === "recording") { recorder.stop(); return; }
  hideError();
  if (!navigator.mediaDevices || !window.MediaRecorder) {
    showError(window.isSecureContext
      ? "This browser can't record audio. Update iOS/Safari, or upload a file instead."
      : "Recording needs a secure (https://) address. Open the app's https link, or upload a file instead.");
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      // Phone voice processing removes "noise" that is often the bird.
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
    });
  } catch {
    showError("Microphone access was blocked. Allow it in your browser settings, or upload a file instead.");
    return;
  }
  const chunks = [];
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.onstop = async () => {
    stream.getTracks().forEach((t) => t.stop());
    clearInterval(timerId);
    keepScreenOn(false);
    setRecordingUi(false);
    if (!chunks.length) { showError("Nothing was recorded. Please try again."); return; }
    try {
      const wav = await toWav(new Blob(chunks, { type: recorder.mimeType }));
      await identify(wav, "recording.wav");
    } catch (err) {
      showError(`Could not process the recording: ${err.message}`);
    }
  };
  recorder.start(1000); // deliver data every second so a cut-short recording isn't lost
  keepScreenOn(true);
  setRecordingUi(true);
  const started = Date.now();
  timerId = setInterval(() => {
    const s = Math.floor((Date.now() - started) / 1000);
    $("#timer").textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    if (s >= MAX_SECONDS && recorder.state === "recording") recorder.stop();
  }, 250);
});

function setRecordingUi(on) {
  $("#record-btn").classList.toggle("recording", on);
  $("#record-label").textContent = on ? "Stop and identify" : "Start recording";
  $("#timer").hidden = !on;
  if (on) $("#timer").textContent = "0:00";
}

// Browsers record compressed audio (webm/ogg/mp4) in different formats. Decode it
// here and send plain WAV so the server always gets something it can read.
async function toWav(blob) {
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const audio = await ctx.decodeAudioData(await blob.arrayBuffer());
  ctx.close();
  const n = audio.length;
  const mono = new Float32Array(n);
  for (let c = 0; c < audio.numberOfChannels; c++) {
    const data = audio.getChannelData(c);
    for (let i = 0; i < n; i++) mono[i] += data[i] / audio.numberOfChannels;
  }
  const buf = new ArrayBuffer(44 + n * 2);
  const v = new DataView(buf);
  const str = (o, s) => [...s].forEach((ch, i) => v.setUint8(o + i, ch.charCodeAt(0)));
  str(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); str(8, "WAVE");
  str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, audio.sampleRate, true); v.setUint32(28, audio.sampleRate * 2, true);
  v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, "data"); v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) {
    const s = Math.max(-1, Math.min(1, mono[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

$("#file-input").addEventListener("change", (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (file) { hideError(); identify(file, file.name); }
});

// ---------- identify ----------
async function identify(blob, filename) {
  const form = new FormData();
  form.append("audio", blob, filename);
  if (coords) { form.append("latitude", coords.lat); form.append("longitude", coords.lon); }
  if ($("#recorded-on").value) form.append("recorded_on", $("#recorded-on").value);

  $("#busy").hidden = false;
  $("#results").innerHTML = "";
  try {
    const resp = await fetch("/api/identify", { method: "POST", body: form });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(errorText(body) || `Server error (${resp.status})`);
    renderResults(body);
  } catch (err) {
    showError(err.message);
  } finally {
    $("#busy").hidden = true;
  }
}

function errorText(body) {
  if (typeof body.detail === "string") return body.detail;
  if (Array.isArray(body.detail)) return body.detail.map((d) => d.msg).join("; ");
  return "";
}

function renderResults(rec) {
  const box = $("#results");
  box.innerHTML = "";
  const others = rec.other_sounds || [];
  if (!rec.detections.length) {
    const card = document.createElement("div");
    card.className = "card empty";
    card.textContent = "No birds recognised. Try a longer or closer recording with less wind and traffic noise.";
    box.appendChild(card);
  }
  rec.detections.forEach((d) => box.appendChild(detectionCard(d)));
  if (others.length) {
    const p = document.createElement("p");
    p.className = "small muted";
    p.textContent = `Also heard (not birds): ${others.join(", ").toLowerCase()}.`;
    box.appendChild(p);
  }
}

function detectionCard(d) {
  const node = $("#detection-tpl").content.firstElementChild.cloneNode(true);
  const pct = Math.round(d.confidence * 100);
  node.querySelector(".common").textContent = d.common_name;
  node.querySelector(".scientific").textContent = d.scientific_name;
  node.querySelector(".score").textContent = `${pct}%`;
  node.querySelector(".fill").style.width = `${pct}%`;

  const meta = node.querySelector(".meta");
  if (d.reported_nearby) {
    const b = document.createElement("span");
    b.className = "badge";
    b.textContent = "Reported nearby on eBird";
    meta.appendChild(b);
  }
  meta.append(`Clearest at ${fmtTime(d.start_s)}–${fmtTime(d.end_s)}` +
    (d.n_segments > 1 ? ` · heard in ${d.n_segments} clips` : ""));

  if (status.xenocanto_enabled) {
    const btn = node.querySelector(".examples-btn");
    btn.hidden = false;
    btn.addEventListener("click", () => loadExamples(d.scientific_name, node.querySelector(".examples"), btn));
  }
  return node;
}

async function loadExamples(scientificName, box, btn) {
  btn.disabled = true;
  btn.textContent = "Loading…";
  try {
    const resp = await fetch(`/api/species/${encodeURIComponent(scientificName)}/recordings`);
    const data = await resp.json();
    box.innerHTML = "";
    if (!data.recordings.length) {
      box.innerHTML = `<p class="small muted">No reference recordings found.</p>`;
    }
    data.recordings.forEach((r) => {
      const div = document.createElement("div");
      div.className = "example";
      const audio = document.createElement("audio");
      audio.controls = true; audio.preload = "none"; audio.src = r.audio_url;
      const credit = document.createElement("p");
      credit.className = "small muted";
      credit.innerHTML = `${esc(r.sound_type || "recording")} · ${esc(r.location || r.country)} ·
        <a href="${esc(r.page_url)}" target="_blank" rel="noopener">XC${esc(r.id)}</a> by ${esc(r.recordist)}
        (<a href="${esc(r.licence_url)}" target="_blank" rel="noopener">licence</a>)`;
      div.append(audio, credit);
      box.appendChild(div);
    });
    btn.hidden = true;
  } catch {
    btn.disabled = false;
    btn.textContent = "Hear examples";
    box.innerHTML = `<p class="small muted">Couldn't load examples.</p>`;
  }
}

// ---------- history ----------
async function loadHistory() {
  const box = $("#history");
  box.innerHTML = `<div class="card empty">Loading…</div>`;
  const recs = await fetch("/api/recordings").then((r) => r.json());
  box.innerHTML = recs.length ? "" : `<div class="card empty">No recordings yet.</div>`;
  recs.forEach((rec) => {
    const card = document.createElement("article");
    card.className = "card history-item";
    const when = new Date(rec.created_at).toLocaleString();
    const birds = rec.detections.length
      ? `<ul>${rec.detections.map((d) =>
          `<li>${esc(d.common_name)} <span class="muted">${Math.round(d.confidence * 100)}%</span></li>`).join("")}</ul>`
      : `<p class="muted small">No birds recognised.</p>`;
    card.innerHTML = `<div class="row"><h3>${esc(when)}</h3>
        <button class="secondary danger small">Delete</button></div>${birds}
        ${rec.has_audio ? `<audio controls preload="none" src="/api/recordings/${rec.id}/audio"></audio>` : ""}`;
    card.querySelector("button").addEventListener("click", async () => {
      if (!confirm("Delete this recording?")) return;
      await fetch(`/api/recordings/${rec.id}`, { method: "DELETE" });
      card.remove();
    });
    box.appendChild(card);
  });
}

// ---------- life list ----------
async function loadLifeList() {
  const box = $("#lifelist");
  box.innerHTML = `<div class="card empty">Loading…</div>`;
  const species = await fetch("/api/life-list").then((r) => r.json());
  box.innerHTML = species.length
    ? `<p class="muted">${species.length} species identified so far.</p>`
    : `<div class="card empty">Species you identify will appear here.</div>`;
  species.forEach((s) => {
    const card = document.createElement("article");
    card.className = "card life-item";
    card.innerHTML = `<div><h3>${esc(s.common_name)}</h3>
        <p class="scientific small">${esc(s.scientific_name)}</p></div>
      <div class="small muted" style="text-align:right">
        First heard ${esc(new Date(s.first_heard).toLocaleDateString())}<br>
        ${s.times_heard} recording${s.times_heard === 1 ? "" : "s"}</div>`;
    box.appendChild(card);
  });
}

// ---------- helpers ----------
function fmtTime(s) {
  const t = Math.round(s);
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
function showError(msg) { const e = $("#error"); e.textContent = msg; e.hidden = false; }
function hideError() { $("#error").hidden = true; }
