// AudioWorklet processors for the browser call.
// pcm-capture: microphone -> 16 kHz mono PCM16 chunks (40 ms) posted to the main thread.
// pcm-player:  Float32 chunks at the context rate -> speakers; {clear: true} flushes (barge-in).

class PcmCapture extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const target = (options.processorOptions && options.processorOptions.targetRate) || 16000;
    this.step = sampleRate / target;
    this.pos = 0;
    this.prev = 0;
    this.size = target / 25;  // samples per 40 ms chunk; kept apart because a sent buffer becomes empty
    this.chunk = new Int16Array(this.size);
    this.n = 0;
    this.levelAcc = 0;
    this.levelN = 0;
  }

  push(s) {
    s = Math.max(-1, Math.min(1, s));
    this.chunk[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
    this.levelAcc += s * s;
    this.levelN++;
    if (this.n === this.size) {
      const out = this.chunk;
      this.port.postMessage({ pcm: out.buffer }, [out.buffer]);
      this.chunk = new Int16Array(this.size);
      this.n = 0;
      this.port.postMessage({ level: Math.sqrt(this.levelAcc / this.levelN) });
      this.levelAcc = 0;
      this.levelN = 0;
    }
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    const at = (k) => (k < 0 ? this.prev : ch[k]);
    while (Math.floor(this.pos) + 1 < ch.length) {
      const i = Math.floor(this.pos);
      const f = this.pos - i;
      this.push(at(i) * (1 - f) + at(i + 1) * f);
      this.pos += this.step;
    }
    this.pos -= ch.length;
    this.prev = ch[ch.length - 1];
    return true;
  }
}

class PcmPlayer extends AudioWorkletProcessor {
  constructor() {
    super();
    this.queue = [];
    this.offset = 0;
    this.port.onmessage = (e) => {
      if (e.data && e.data.clear) { this.queue = []; this.offset = 0; return; }
      this.queue.push(e.data);
    };
  }

  process(_inputs, outputs) {
    const out = outputs[0][0];
    let i = 0;
    while (i < out.length && this.queue.length) {
      const head = this.queue[0];
      const take = Math.min(out.length - i, head.length - this.offset);
      out.set(head.subarray(this.offset, this.offset + take), i);
      i += take;
      this.offset += take;
      if (this.offset >= head.length) { this.queue.shift(); this.offset = 0; }
    }
    out.fill(0, i);
    for (let c = 1; c < outputs[0].length; c++) outputs[0][c].set(out);
    return true;
  }
}

registerProcessor("pcm-capture", PcmCapture);
registerProcessor("pcm-player", PcmPlayer);
