import { pickLine } from "./stand-in.js";
import { cfg, cropLabel, el, fmtKg, KIND_WORD, pill, plainPrice, subscribe, toast, wsUrl } from "./data.js";

const $ = (id) => document.getElementById(id);
const OUTPUT_RATE = 24000;
const STAGES = ["Open", "Collect", "Confirm", "Offer", "Counter", "Close"];

$("ai-badge-text").textContent = `AI agent calling for ${cfg.millName}`;

let state = { calls: [], farmers: [] };
let active = null; // the call in progress
const calm = matchMedia("(prefers-reduced-motion: reduce)");

function show(view) {
  for (const v of ["waiting", "call", "ended"]) $(`view-${v}`).hidden = v !== view;
}

// ---------- incoming list ----------

subscribe((s) => { state = s; if (!active) renderIncoming(); });

function farmerOf(call) {
  return state.farmers.find((f) => f.id === call.farmer_id) || {};
}

function renderIncoming() {
  const queued = state.calls.filter((c) => c.status === "queued")
    .sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));
  $("incoming").replaceChildren(...(queued.length ? queued.map((c) => {
    const f = farmerOf(c);
    const what = c.kind === "gap_fill" ? `Gap-fill call for week ${c.gap_week}` : KIND_WORD[c.kind];
    return el("li", {},
      el("div", { class: "meta" }, el("b", {}, c.farmer_name),
        el("small", {}, [f.village, what, c.attempt > 1 ? "retry" : null].filter(Boolean).join(" · "))),
      el("button", { class: "btn mint", onclick: () => answer(c) }, "Answer"));
  }) : [el("li", { class: "none" }, "No calls waiting. Start calling on the Campaign page, or press Call now next to a farmer.")]));
}

// ---------- call ----------

function openCallView(call) {
  $("call-farmer").textContent = call.farmer_name;
  $("captions").replaceChildren(el("p", { class: "hint" }, "Captions appear here as you and the agent speak."));
  for (const id of ["captured", "rail", "offer-saved"]) $(id).hidden = true;
  $("consent").textContent = "The agent asks for consent before a transcript is kept.";
  $("mute").textContent = "Mute";
  $("mute").setAttribute("aria-pressed", "false");
  $("stand-in-row").hidden = false;
  $("stand-in").textContent = STAND_IN_LABEL;
  $("stand-in").setAttribute("aria-pressed", "false");
  setStage(0);
  meta("Connecting…");
  show("call");
  $("mic-note").hidden = true;
}

async function answer(call) {
  if (active) return;
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch {
    toast("Microphone access is needed to answer. Allow it in the browser and try again.", true);
    return;
  }
  const ctx = new AudioContext();
  // Some browsers create the audio engine paused (autoplay rules); a paused engine hears and plays nothing.
  if (ctx.state !== "running") await ctx.resume().catch(() => {});
  const micName = stream.getAudioTracks()[0]?.label || "your default microphone";
  await ctx.audioWorklet.addModule("js/audio-worklets.js");
  const source = ctx.createMediaStreamSource(stream);
  const capture = new AudioWorkletNode(ctx, "pcm-capture", { processorOptions: { targetRate: 16000 } });
  const silent = ctx.createGain();
  silent.gain.value = 0;
  source.connect(capture).connect(silent).connect(ctx.destination);
  const player = new AudioWorkletNode(ctx, "pcm-player", { outputChannelCount: [1] });
  const volume = ctx.createGain();
  volume.gain.value = volumeGain(Number($("volume").value));
  player.connect(volume).connect(ctx.destination);

  const ws = new WebSocket(wsUrl(`/ws/call/${call.id}`));
  ws.binaryType = "arraybuffer";
  const f = farmerOf(call);
  active = { call, ws, ctx, stream, player, volume, micName, startedAt: Date.now(), playEnd: 0, ended: false, muted: false,
    stage: 0, lines: {}, village: f.village, language: f.language, gapWeek: call.gap_week };

  openCallView(call);
  $("replay-note").hidden = true;
  active.timer = setInterval(() => { meta(); micCheck(); }, 500);

  capture.port.onmessage = (e) => {
    const standIn = active?.standIn?.on ? active.standIn : null;
    if (e.data.level !== undefined) return standIn ? undefined : hearYou(e.data.level);
    if (active) active.made = (active.made || 0) + 1;  // chunks the microphone worklet produced
    // With the stand-in farmer on, the scripted clip (or silence between lines) replaces the microphone,
    // chunk for chunk, so the model hears a steady stream like a real call.
    const pcm = standIn ? standInChunk(standIn, e.data.pcm.byteLength / 2) : e.data.pcm;
    if (pcm && ws.readyState === WebSocket.OPEN && (standIn || !active?.muted)) {
      ws.send(pcm);
      active.sent = (active.sent || 0) + 1;  // chunks actually sent to the server
    }
  };
  active.voiceTimer = setInterval(showVoices, 80);

  ws.onmessage = (e) => {
    if (e.data instanceof ArrayBuffer) return play(e.data);
    handleMessage(JSON.parse(e.data));
  };
  ws.onclose = () => { if (active && !active.ended) finish({ status: "dropped", kind: call.kind }); };
}

// One server message (from the live socket or from a sample call) -> the call screen.
function handleMessage(msg) {
  if (!active) return;
  if (msg.type === "connected") { Object.assign(active, { village: msg.village, language: msg.language, gapWeek: msg.gap_week }); active.connected = true; meta(); }
  else if (msg.type === "caption") {
    if (msg.who === "agent") {  // the agent's latest turn, for the stand-in farmer to answer
      if (active.agentIndex !== msg.index) { active.agentIndex = msg.index; active.agentText = ""; }
      active.agentText += msg.text;
    }
    caption(msg);
  }
  else if (msg.type === "translation") translation(msg);
  else if (msg.type === "interrupted") flush();
  else if (msg.type === "tool") { active.lastTool = performance.now(); toolEvent(msg); }
  else if (msg.type === "error") toast(msg.message, true);
  else if (msg.type === "ended") finish(msg);
}

// ---------- sample call: a scripted call replayed on the same screen, for when no one can play the farmer ----------

const SAMPLE_URL = "samples/gap-fill.json";

// The sample's clips are decoded up front (the click that starts the replay allows sound), so playback starts on time.
async function loadSampleAudio(sample, actx) {
  const urls = [...new Set(sample.events.filter((e) => e.audio).map((e) => e.audio))];
  if (!urls.length) return null;
  try {
    const gain = actx.createGain();
    gain.gain.value = volumeGain(Number($("volume").value));
    gain.connect(actx.destination);
    const buffers = new Map(await Promise.all(urls.map(async (u) => [u, await actx.decodeAudioData(await (await fetch(u)).arrayBuffer())])));
    return { ctx: actx, gain, buffers, sources: [] };
  } catch {
    toast("The sample call's sound could not be loaded. It plays without sound.", true);
    return null;
  }
}

async function replay() {
  if (active) return;
  let actx = null;
  try {
    actx = new AudioContext();
    if (actx.state !== "running") await actx.resume().catch(() => {});
  } catch { /* no audio engine: the sample still plays as captions */ }
  let sample;
  try {
    sample = await (await fetch(SAMPLE_URL)).json();
  } catch {
    toast("The sample call could not be loaded.", true);
    actx?.close();
    return;
  }
  const audio = actx && sample.audio ? await loadSampleAudio(sample, actx) : null;
  if (!audio) actx?.close();
  if (active) return;
  const clock0 = performance.now();
  const ctx = { state: "running", sampleRate: 48000, get currentTime() { return (performance.now() - clock0) / 1000; }, close() {}, resume() { return Promise.resolve(); } };
  const call = { id: "sample", kind: sample.kind, farmer_name: sample.farmer, gap_week: sample.gap_week };
  active = { call, ws: { readyState: WebSocket.OPEN, send() {}, close() {} }, ctx, stream: null, player: { port: { postMessage() {} } },
    volume: audio ? audio.gain : { gain: { value: 1 } }, replayAudio: audio, micName: "", startedAt: Date.now(), playEnd: 0, ended: false, muted: false, stage: 0, lines: {},
    village: sample.village, language: sample.language, gapWeek: sample.gap_week, replay: true, timeouts: [] };
  openCallView(call);
  $("replay-note").textContent = audio ? "Sample call: a recording, not a live call. Nothing is saved." : "Sample call: a recording shown without sound, not a live call. Nothing is saved.";
  $("replay-note").hidden = false;
  $("stand-in-row").hidden = true;
  active.timer = setInterval(() => meta(), 500);
  active.voiceTimer = setInterval(showVoices, 80);
  const speak = (ms) => { active.playEnd = Math.max(active.playEnd, ctx.currentTime) + ms / 1000; };
  const farmerSpeaks = (ms) => { active.micLevel = 0.7; setTimeout(() => { if (active) active.micLevel = 0; }, ms); };
  for (const ev of sample.events) {
    active.timeouts.push(setTimeout(() => {
      if (!active) return;
      const buf = ev.audio && audio ? audio.buffers.get(ev.audio) : null;
      if (buf) {
        const src = audio.ctx.createBufferSource();
        src.buffer = buf;
        src.connect(audio.gain);
        src.start();
        audio.sources.push(src);
        if (ev.who === "agent") speak(buf.duration * 1000); else farmerSpeaks(buf.duration * 1000);
      }
      const msg = ev.msg;
      if (!msg) return;
      if (msg.type === "caption" && !audio) {
        // No sound: show who is talking for about as long as the words take to say.
        if (msg.who === "agent") speak(msg.text.length * 70); else farmerSpeaks(Math.min(6000, 700 + msg.text.length * 55));
      }
      handleMessage(msg);
    }, ev.t));
  }
}

function stopReplay() {
  if (!active?.replay) return;
  active.timeouts.forEach(clearTimeout);
  clearInterval(active.timer);
  clearInterval(active.voiceTimer);
  active.replayAudio?.sources.forEach((src) => { try { src.stop(); } catch { /* already finished */ } });
  active.replayAudio?.ctx.close().catch(() => {});
  active = null;
  $("replay-note").hidden = true;
  show("waiting");
  renderIncoming();
}

// ---------- stand-in farmer: scripted farmer audio sent into a live call ----------
// "Play the farmer for me" replaces the microphone with the farmer's lines from samples/farmer-lines.json (spoken
// by Gemini, the same clips the sample call uses). Each time the agent has finished talking, the line that answers
// what it just said is chosen (stand-in.js: pickLine), so the call keeps its sense when the agent varies its order.

const FARMER_LINES_URL = "samples/farmer-lines.json";
const STAND_IN_LABEL = "Play the farmer for me";

function parseWav(buf) {  // 16 kHz mono PCM16 WAV -> Int16Array
  const view = new DataView(buf);
  for (let pos = 12; pos + 8 <= buf.byteLength;) {
    const size = view.getUint32(pos + 4, true);
    if (String.fromCharCode(...new Uint8Array(buf, pos, 4)) === "data") return new Int16Array(buf.slice(pos + 8, pos + 8 + size));
    pos += 8 + size + (size & 1);
  }
  throw new Error("not a WAV file");
}

async function loadFarmerLines() {
  const meta = await (await fetch(FARMER_LINES_URL)).json();
  const clips = new Map();  // several lines may share one clip
  await Promise.all([...new Set(meta.map((l) => l.audio))].map(async (u) => clips.set(u, parseWav(await (await fetch(u)).arrayBuffer()))));
  return { meta, clips };
}

function setStandIn(on) {
  const s = active?.standIn;
  if (!s) return;
  s.on = on;
  if (!on) { s.clip = null; active.micLevel = 0; }
  $("stand-in").setAttribute("aria-pressed", String(on));
  $("stand-in").textContent = on ? "Stop playing the farmer" : STAND_IN_LABEL;
}

function agentDone(s) {
  const now = performance.now();
  return active.lastAgentAudio > s.endedAt                       // the agent has answered the last line (or opened the call)
    && now - active.lastAgentAudio >= 1600                       // and has stopped generating (agents pause mid-turn)
    && active.ctx.currentTime >= active.playEnd + 0.6            // and has finished playing
    && now - (active.lastTool || 0) >= 2500;                     // and is not in the middle of a tool call
}

function standInChunk(s, samples) {
  const out = new Int16Array(samples);
  if (!s.clip && agentDone(s)) {
    const i = pickLine(s.lines.meta, active.agentText, s.used);
    if (i < 0) {
      setStandIn(false);
      toast("The scripted farmer has no answer for that. Your microphone is back on.");
    } else {
      const line = s.lines.meta[i];
      s.used[line.id] = (s.used[line.id] || 0) + 1;
      s.clip = s.lines.clips.get(line.audio);
      s.pos = 0;
      s.ends = !!line.ends;
    }
  }
  if (s.clip) {
    out.set(s.clip.subarray(s.pos, s.pos + samples));
    s.pos += samples;
    active.micLevel = 0.7;
    active.heardAt = Date.now();
    if (s.pos >= s.clip.length) {
      s.clip = null;
      s.endedAt = performance.now();
      active.micLevel = 0;
      if (s.ends) { setStandIn(false); toast("The scripted farmer has said goodbye. Your microphone is back on."); }
    }
  } else {
    active.micLevel = 0;
  }
  return out.buffer;
}

$("stand-in").onclick = async () => {
  if (!active || active.replay) return;
  const s = active.standIn ||= { lines: null, used: {}, clip: null, pos: 0, endedAt: 0, on: false, ends: false };
  if (s.on) return setStandIn(false);
  if (!s.lines) {
    try { s.lines = await loadFarmerLines(); } catch { toast("The scripted farmer's lines could not be loaded.", true); return; }
  }
  if (s.used.closing) { toast("The scripted farmer has already said goodbye.", true); return; }
  setStandIn(true);
};

// ---------- who is speaking: mic level for the farmer, playback for the agent ----------
// The "You" bars show what the browser hears, so "it does not answer me" can be told apart from
// "it cannot hear me". Speech is roughly 0.02 to 0.2 RMS.

function hearYou(rms) {
  if (!active) return;
  // Map the RMS to 0..1 on a log-ish scale for the bars.
  active.micLevel = active.muted ? 0 : Math.min(1, Math.max(0, (Math.log10(rms + 1e-4) + 3) / 2.2));
  active.maxLevel = Math.max(active.maxLevel || 0, rms);
  if (rms > 0.008) active.heardAt = Date.now();
}

function showVoices() {
  if (!active) return;
  const talking = active.playEnd > active.ctx.currentTime + 0.05;
  const you = active.micLevel || 0;
  const t = performance.now() / 1000;
  const set = (id, on, level) => {
    const box = $(id);
    box.classList.toggle("on", on);
    box.querySelectorAll("i").forEach((bar, k) => {
      const wave = calm.matches ? [0.6, 0.9, 1, 0.8, 0.55][k] : 0.55 + 0.45 * Math.sin(t * 9 + k * 1.3);
      bar.style.transform = `scaleY(${on ? Math.max(0.18, level * wave) : 0.18})`;
    });
  };
  set("voice-agent", talking, 0.85);
  set("voice-you", you > 0.35, you);
}

function micCheck() {
  if (!active) return;
  const note = $("mic-note");
  if (active.ctx.state !== "running") {
    note.textContent = "Your browser has paused the call's audio. Tap anywhere on this page to start it.";
    note.hidden = false;
    active.ctx.resume().catch(() => {});
  } else if (active.standIn?.on) {
    note.textContent = "A scripted farmer is speaking for you. Your microphone is not used.";
    note.hidden = false;
  } else if (active.muted) {
    note.textContent = "Muted: the agent cannot hear you.";
    note.hidden = false;
  } else if (!active.heardAt && Date.now() - active.startedAt > 6000
             && active.playEnd < active.ctx.currentTime - 6) {  // 6 s of quiet after the agent stopped talking
    note.textContent = `No sound from "${active.micName}" yet. Check that it is not muted in your system, and that the right microphone is chosen in the browser's site settings. (Loudest level so far: ${(active.maxLevel || 0).toFixed(4)}; speech is about 0.02 to 0.2. Audio chunks made: ${active.made || 0}, sent: ${active.sent || 0}, audio engine: ${active.ctx.state}, connection: ${["connecting", "open", "closing", "closed"][active.ws.readyState]}.)`;
    note.hidden = false;
  } else {
    note.hidden = true;
  }
}

function clock() {
  const s = Math.floor((Date.now() - active.startedAt) / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

function meta(override) {
  if (!active) return;
  if (override) { $("call-meta").textContent = override; return; }
  if (!active.connected) return;
  const t = `on call ${clock()}`;
  const k = active.call.kind;
  $("call-meta").textContent = k === "gap_fill" ? `Gap-fill call for week ${active.gapWeek} · ${t}`
    : k === "confirm" ? `Confirmation call · ${t}`
    : [active.village, t, active.language].filter(Boolean).join(" · ");
}

function setStage(i) {
  if (!active) return;
  active.stage = Math.max(active.stage, i);
  $("stages").replaceChildren(...STAGES.map((name, n) =>
    el("li", { class: n < active.stage ? "done" : n === active.stage ? "now" : "", "aria-current": n === active.stage ? "step" : null }, name)));
}

function play(buf) {
  const { ctx, player } = active;
  active.lastAgentAudio = performance.now();
  const pcm = new Int16Array(buf);
  const ratio = ctx.sampleRate / OUTPUT_RATE;
  const out = new Float32Array(Math.round(pcm.length * ratio));
  for (let i = 0; i < out.length; i++) {
    const x = i / ratio;
    const j = Math.floor(x);
    const fr = x - j;
    const a = pcm[j] || 0;
    const b = pcm[Math.min(j + 1, pcm.length - 1)] || 0;
    out[i] = (a * (1 - fr) + b * fr) / 0x8000;
  }
  player.port.postMessage(out, [out.buffer]);
  active.playEnd = Math.max(active.playEnd, ctx.currentTime) + out.length / ctx.sampleRate;
}

function flush() {
  if (!active) return;
  active.player.port.postMessage({ clear: true });
  active.playEnd = active.ctx.currentTime;
}

// Keep the newest line in view, unless the reader scrolled up to reread something.
function nearBottom(box) { return box.scrollHeight - box.scrollTop - box.clientHeight < 60; }
function follow(box, stick) {
  if (stick) box.scrollTop = box.scrollHeight; // instant, so the next line still finds us at the bottom
}

function caption({ who, text, index }) {
  const box = $("captions");
  const stick = nearBottom(box);
  box.querySelector(".hint")?.remove();
  let line = active.lines[index];
  if (!line) {
    const txt = el("span", { class: "txt" });
    const tr = el("span", { class: "tr" });
    const node = el("div", { class: `bubble ${who}` }, el("span", { class: "who" }, who === "agent" ? "Agent" : active.call.farmer_name), txt, tr);
    line = active.lines[index] = { txt, tr };
    box.append(node);
    if (who === "farmer") setStage(active.call.kind === "confirm" ? 5 : 1);
  }
  line.txt.textContent += text;
  follow(box, stick);
}

function translation({ index, text }) {
  const line = active?.lines[index];
  if (!line) return;
  const box = $("captions");
  const stick = nearBottom(box);
  line.tr.textContent = text;
  follow(box, stick);
}

function toolEvent({ name, args, result, ui }) {
  if (ui?.captured) { active.captured = ui.captured; renderCaptured(ui.captured); }
  if (ui?.offer_saved) active.saved = ui.offer_saved;
  if (ui?.rail) renderRail(ui.rail);
  if (ui?.offer_saved) renderSaved(ui.offer_saved);
  if (ui && "consent" in ui) {
    $("consent").textContent = ui.consent ? `Consent given. Transcript is saved for ${cfg.millName}.` : "No consent. The transcript is not kept.";
  }
  if (result?.error) return;
  if (name === "record_harvest") setStage(result.saved ? 3 : 2);
  else if (name === "get_reference_price") setStage(3);
  else if (name === "check_offer") setStage(args && args.farmer_counter_price ? 4 : 3);
  else if (name === "save_offer" || name === "end_call") setStage(5);
}

function renderCaptured(c) {
  const box = $("captured");
  box.hidden = false;
  box.replaceChildren(
    el("div", { class: "head" }, el("span", { class: "title" }, "Captured"),
      c.status === "saved" ? pill("Saved", "leaf") : pill("Waiting for read-back", "amber")),
    kv([["Crop", c.crop], ["Volume", `${fmtKg(c.kg)} kg`],
      ["Ready", c.ready.replace(" · ", ", ").replace(/^W(\d+)/, "Week $1")], ["Confidence", c.confidence]]));
}

function kv(pairs) {
  return el("div", { class: "kv" }, pairs.flatMap(([k, v]) => [el("span", {}, k), el("span", {}, v)]));
}

function renderRail(r) {
  const box = $("rail");
  box.hidden = false;
  $("captured").hidden = true; // during the offer the price rail replaces the captured answers
  const cur = r.currency || "IDR";
  const lo = r.floor;
  const hi = r.ceiling + (r.ceiling - r.floor) * 0.15;
  const pos = (v) => `${Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100))}%`;
  const out = r.counter && r.counter > r.ceiling;
  const chip = r.decision === "escalate" ? pill("Above ceiling", "danger") : r.decision === "accept" ? pill("Allowed", "leaf") : pill("Offer", "leaf");
  const fn = r.counter ? `check_offer(${plainPrice(r.counter, cur)}, ${fmtKg(r.kg)} kg)` : `check_offer(${fmtKg(r.kg)} kg)`;
  const track = el("div", { class: "track", "aria-hidden": "true" },
    el("div", { class: "base" }),
    el("div", { class: "band", style: `left:${pos(r.reference)};right:${100 - parseFloat(pos(r.ceiling))}%` }),
    el("div", { class: "mark", style: `left:${pos(r.reference)}` }),
    r.offer ? el("div", { class: "mark offer", style: `left:${pos(r.offer)}` }) : null,
    r.counter ? el("div", { class: `mark ask ${out ? "out" : ""}`, style: `left:${pos(r.counter)}` }) : null);
  const third = r.counter ? ["Counter", r.counter] : ["Offer", r.offer];
  const ticks = el("div", { class: "ticks" },
    el("span", {}, "Floor", el("strong", { class: "num" }, plainPrice(r.floor, cur))),
    el("span", {}, "Reference", el("strong", { class: "num" }, plainPrice(r.reference, cur))),
    el("span", {}, third[0], el("strong", { class: "num" }, plainPrice(third[1], cur))),
    el("span", {}, "Ceiling", el("strong", { class: "num" }, plainPrice(r.ceiling, cur))));
  const explain = r.decision === "escalate"
    ? "Above the ceiling. The agent offers its best price for less volume, or hands the request to the planner."
    : r.decision === "accept"
      ? "Inside the ceiling, so the agent may accept. Above it, the agent would offer less volume or hand over to the planner."
      : "Reference price plus a small premium, below the ceiling. The price comes from code, not the model.";
  box.replaceChildren(el("div", { class: "head" }, el("span", { class: "fn" }, fn), chip), track, ticks, el("div", { class: "explain" }, explain));
}

function renderSaved(o) {
  const box = $("offer-saved");
  box.hidden = false;
  box.replaceChildren(o.status === "pending" ? pill("Offer saved · pending approval", "amber") : pill("Sent to the planner", "danger"),
    el("span", { class: "sub", style: "margin:0" }, "Synthetic prices"));
}

function finish(msg) {
  if (!active || active.ended) return;
  active.ended = true;
  const a = active;
  const wait = Math.max(0, (a.playEnd - a.ctx.currentTime) * 1000) + 300;
  meta("Ending…");
  setTimeout(() => {
    clearInterval(a.timer);
    clearInterval(a.voiceTimer);
    a.stream?.getTracks().forEach((t) => t.stop());
    a.ctx.close();
    a.replayAudio?.ctx.close().catch(() => {});
    $("replay-note").hidden = true;
    if (a.ws.readyState <= WebSocket.OPEN) a.ws.close();
    active = null;
    renderEnded(a, msg);
    show("ended");
  }, wait);
}

function renderEnded(a, msg) {
  $("ended-farmer").textContent = a.call.farmer_name;
  const words = { done: "Call finished", declined: "Farmer declined or asked to stop", dropped: "Call dropped" };
  const secs = Math.round((Date.now() - a.startedAt) / 1000);
  $("ended-meta").textContent = `${KIND_WORD[a.call.kind]} · ${words[msg.status] || msg.status || "ended"} · ${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
  const cur = (d) => (d.currency === "IDR" || !d.currency ? "Rp " : "");

  // The outcome card says in one line what changed for the mill, then the facts.
  let tone = "ok", glyph = "check", title = "Call finished", facts = [];
  const c = a.captured, saved = a.saved;
  if (msg.status === "dropped") {
    tone = "warn"; glyph = "alert"; title = "Call dropped";
  } else if (msg.status === "declined") {
    tone = "muted"; glyph = "x"; title = "Farmer declined";
  } else if (msg.deal) {
    const d = msg.deal;
    const start = d.deliver_start ? new Date(d.deliver_start + "T00:00:00").toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" }) : "";
    title = "Deal confirmed";
    facts = [["Volume", `${fmtKg(d.kg)} kg ${cropLabel(d.crop)}`], ["Price", `${cur(d)}${plainPrice(d.price_per_kg, d.currency)} / kg`],
      ["Delivery", `Week ${d.deliver_week}${start ? `, from ${start}` : ""}`],
      ["Forecast", d.from_week ? `Moved from week ${d.from_week} to week ${d.deliver_week}` : `Added to week ${d.deliver_week}`]];
    if (d.decided_by) facts.push(["Approved by", d.decided_by]);
  } else if (saved) {
    tone = saved.status === "pending" ? "ok" : "warn";
    title = saved.status === "pending" ? "Offer sent for approval" : "Sent to the planner: price above the ceiling";
    facts = [["Volume", `${fmtKg(saved.kg)} kg`]];
    if (saved.price) facts.push(["Price", `Rp ${plainPrice(saved.price, "IDR")} / kg`]);
    facts.push(["Next", "The planner approves or rejects it on the Approvals page"]);
  } else if (c && c.status === "saved") {
    title = "Harvest recorded";
    facts = [["Volume", `${fmtKg(c.kg)} kg ${c.crop}`], ["Ready", c.ready], ["Answer", c.confidence === "Unsure" ? "Unsure, counted half" : "Firm"]];
  }
  const body = [el("div", { class: `outcome ${tone}` },
    el("div", { class: "head" }, el("span", { class: "glyph", "aria-hidden": "true" }, glyph === "check" ? "✓" : glyph === "x" ? "✕" : "!"),
      el("h2", {}, title)),
    facts.length ? kv(facts) : null,
    msg.status === "dropped" ? el("p", {}, msg.retry_queued
      ? "Answers saved during the call are kept, and the call is queued again once."
      : "Answers saved during the call are kept.") : null,
    msg.summary ? el("div", { class: "summary" }, el("span", {}, "Summary for the planner"), el("p", {}, msg.summary)) : null)];
  if (msg.consent !== undefined && msg.status !== "dropped") {
    body.push(el("p", { class: "consent" }, msg.consent ? `Consent given. Transcript is saved for ${cfg.millName}.` : "No consent. The transcript is not kept."));
  }
  $("ended-body").replaceChildren(...body);
}

// ---------- agent volume ----------
// The slider is 0..100; squaring it gives finer control at the quiet end, where it is needed most.
const VOLUME_KEY = "harvestCallVolume";
const volumeGain = (percent) => (percent / 100) ** 2;

function savedVolume() {
  try {
    const raw = localStorage.getItem(VOLUME_KEY);
    const v = Number(raw);
    return raw !== null && v >= 0 && v <= 100 ? v : 100;
  } catch { return 100; }
}

$("volume").value = savedVolume();
$("volume-out").textContent = `${$("volume").value}%`;
$("volume").oninput = () => {
  const v = Number($("volume").value);
  $("volume-out").textContent = `${v}%`;
  if (active) active.volume.gain.value = volumeGain(v);
  try { localStorage.setItem(VOLUME_KEY, String(v)); } catch { /* storage blocked: the slider still works */ }
};

// A tap or click is a user gesture, which lets a paused audio engine start.
document.addEventListener("pointerdown", () => { if (active && active.ctx.state !== "running") active.ctx.resume().catch(() => {}); });

$("hangup").onclick = () => {
  if (!active) return;
  if (active.replay) return stopReplay();
  if (active.ws.readyState === WebSocket.OPEN) active.ws.send(JSON.stringify({ type: "hangup" }));
  flush();
};
$("mute").onclick = () => {
  if (!active) return;
  active.muted = !active.muted;
  $("mute").textContent = active.muted ? "Unmute" : "Mute";
  $("mute").setAttribute("aria-pressed", String(active.muted));
};
$("back").onclick = () => { show("waiting"); renderIncoming(); };
$("sample").onclick = replay;
if (new URLSearchParams(location.search).has("sample")) replay();
