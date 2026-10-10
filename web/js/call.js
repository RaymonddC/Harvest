import { cfg, cropLabel, el, fmtKg, KIND_WORD, pill, plainPrice, subscribe, toast, wsUrl } from "./data.js";

const $ = (id) => document.getElementById(id);
const OUTPUT_RATE = 24000;
const STAGES = ["Open", "Collect", "Confirm", "Offer", "Counter", "Close"];

$("ai-badge-text").textContent = `AI agent calling for ${cfg.millName}`;

let state = { calls: [], farmers: [] };
let active = null; // the call in progress

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
  }) : [el("li", { class: "none" }, "No calls waiting. Start the campaign on the Setup page, or press Call now next to a farmer.")]));
}

// ---------- call ----------

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
  await ctx.audioWorklet.addModule("js/audio-worklets.js");
  const source = ctx.createMediaStreamSource(stream);
  const capture = new AudioWorkletNode(ctx, "pcm-capture", { processorOptions: { targetRate: 16000 } });
  const silent = ctx.createGain();
  silent.gain.value = 0;
  source.connect(capture).connect(silent).connect(ctx.destination);
  const player = new AudioWorkletNode(ctx, "pcm-player", { outputChannelCount: [1] });
  player.connect(ctx.destination);

  const ws = new WebSocket(wsUrl(`/ws/call/${call.id}`));
  ws.binaryType = "arraybuffer";
  const f = farmerOf(call);
  active = { call, ws, ctx, stream, player, startedAt: Date.now(), playEnd: 0, ended: false, muted: false,
    stage: 0, lines: {}, village: f.village, language: f.language, gapWeek: call.gap_week };

  $("call-farmer").textContent = call.farmer_name;
  $("captions").replaceChildren(el("p", { class: "hint" }, "Captions appear here as you and the agent speak."));
  for (const id of ["captured", "rail", "offer-saved"]) $(id).hidden = true;
  $("consent").textContent = "The agent asks for consent before a transcript is kept.";
  $("mute").textContent = "Mute";
  $("mute").setAttribute("aria-pressed", "false");
  setStage(0);
  meta("Connecting…");
  show("call");
  $("mic-fill").style.width = "0";
  $("mic-note").hidden = true;
  active.timer = setInterval(() => { meta(); micCheck(); }, 500);

  capture.port.onmessage = (e) => {
    if (e.data.level !== undefined) return micLevel(e.data.level);
    if (e.data.pcm && ws.readyState === WebSocket.OPEN && !active?.muted) ws.send(e.data.pcm);
  };

  ws.onmessage = (e) => {
    if (e.data instanceof ArrayBuffer) return play(e.data);
    const msg = JSON.parse(e.data);
    if (msg.type === "connected") { Object.assign(active, { village: msg.village, language: msg.language, gapWeek: msg.gap_week }); active.connected = true; meta(); }
    else if (msg.type === "caption") caption(msg);
    else if (msg.type === "translation") translation(msg);
    else if (msg.type === "interrupted") flush();
    else if (msg.type === "tool") toolEvent(msg);
    else if (msg.type === "error") toast(msg.message, true);
    else if (msg.type === "ended") finish(msg);
  };
  ws.onclose = () => { if (active && !active.ended) finish({ status: "dropped", kind: call.kind }); };
}

// The level bar shows what the browser hears, so "it does not answer me" can be told apart from
// "it cannot hear me". Speech is roughly 0.02 to 0.2 RMS.
function micLevel(rms) {
  if (!active) return;
  $("mic-fill").style.width = `${Math.min(100, Math.round(rms * 600))}%`;
  if (rms > 0.008) active.heardAt = Date.now();
}

function micCheck() {
  if (!active) return;
  const note = $("mic-note");
  if (active.muted) {
    note.textContent = "Muted: the agent cannot hear you.";
    note.hidden = false;
  } else if (!active.heardAt && Date.now() - active.startedAt > 6000) {
    note.textContent = "No sound from your microphone yet. Check that it is not muted in your system and that the right one is allowed in the browser's site settings.";
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

function caption({ who, text, index }) {
  const box = $("captions");
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
  box.scrollTop = box.scrollHeight;
}

function translation({ index, text }) {
  const line = active?.lines[index];
  if (line) line.tr.textContent = text;
}

function toolEvent({ name, args, result, ui }) {
  if (ui?.captured) renderCaptured(ui.captured);
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
    a.stream.getTracks().forEach((t) => t.stop());
    a.ctx.close();
    if (a.ws.readyState <= WebSocket.OPEN) a.ws.close();
    active = null;
    renderEnded(a, msg);
    show("ended");
  }, wait);
}

function renderEnded(a, msg) {
  $("ended-farmer").textContent = a.call.farmer_name;
  const words = { done: "Call finished", declined: "Farmer declined or asked to stop", dropped: "Call dropped" };
  $("ended-meta").textContent = `${KIND_WORD[a.call.kind]} · ${words[msg.status] || msg.status || "ended"}`;
  const body = [];
  if (msg.deal && msg.status === "done") {
    const d = msg.deal;
    const start = d.deliver_start ? new Date(d.deliver_start + "T00:00:00").toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" }) : "";
    body.push(el("div", { class: "panel deal" },
      el("div", { class: "head" }, el("span", { class: "serif" }, "Deal confirmed"), d.decided_by ? pill(`Approved by ${d.decided_by}`, "leaf") : null),
      kv([["Volume", `${fmtKg(d.kg)} kg ${cropLabel(d.crop)}`], ["Price", `${d.currency === "IDR" ? "Rp " : ""}${plainPrice(d.price_per_kg, d.currency)} / kg`],
        ["Delivery", `Week ${d.deliver_week}${start ? `, from ${start}` : ""}`],
        ["Forecast", d.from_week ? `Moved from week ${d.from_week} to week ${d.deliver_week}` : `Added to week ${d.deliver_week}`]])));
  }
  if (msg.status === "dropped") {
    body.push(el("div", { class: "summary-box" }, msg.retry_queued
      ? "The call dropped. Answers saved during the call are kept, and the call is queued again once."
      : "The call dropped. Answers saved during the call are kept."));
  }
  if (msg.summary) body.push(el("div", { class: "summary-box" }, el("strong", {}, "Summary for the planner: "), msg.summary));
  if (msg.consent !== undefined && msg.status !== "dropped") {
    body.push(el("p", { class: "consent" }, msg.consent ? `Consent given. Transcript is saved for ${cfg.millName}.` : "No consent. The transcript is not kept."));
  }
  $("ended-body").replaceChildren(...body);
}

$("hangup").onclick = () => {
  if (!active) return;
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
