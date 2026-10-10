// Runs web/js/audio-worklets.js outside a browser and prints how many 40 ms chunks the capture
// processor posts for 4 s of audio. Posting a buffer empties it, as in a real browser.
import fs from "fs";
const src = fs.readFileSync(process.argv[2], "utf8");
let Cls; const posted = [];
globalThis.sampleRate = 48000;
globalThis.AudioWorkletProcessor = class {
  constructor() { this.port = { postMessage: (m, tr) => { if (tr) structuredClone(m, { transfer: tr }); posted.push(m); }, onmessage: null }; }
};
globalThis.registerProcessor = (n, c) => { if (n === "pcm-capture") Cls = c; };
new Function(src)();
const p = new Cls({ processorOptions: { targetRate: 16000 } });
for (let i = 0; i < 1500; i++) p.process([[new Float32Array(128).map((_, k) => Math.sin((i * 128 + k) / 20) * 0.3)]]);
console.log(posted.filter((m) => m.pcm).length);
