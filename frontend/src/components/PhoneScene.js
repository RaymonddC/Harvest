import * as THREE from "three";

// The sign-in page's picture: a phone floating in the panel, playing a call on its screen. It rings ("Calling Pak
// Wahyu"), connects, and plays a short harvest call line by line (what the agent asks, how it reads the answer
// back), then the result the system saved; then it starts again. An illustration in English, not a recording. Soft rings spread
// behind it while the call is on. Plain Three.js, loaded only on this page.
//
// startPhone(canvas, { still }) returns a stop() function that removes everything it added.
// still: one frame showing the saved result, no motion (the "reduce motion" setting).

const W = 540, H = 1080; // the screen texture, 1:2
const FONT = '"Plus Jakarta Sans", system-ui, sans-serif';
const C = { bg: "#0E1512", bar: "#16201B", agent: "#16774E", farmer: "#22302A", text: "#FFFFFF", sub: "#B9C2BD",
  en: "#9FD9BC", mint: "#7FE0B4", card: "#EAF6EF", cardText: "#0F3D2A" };

// One harvest call, start to finish: the AI says who it is, asks, reads the answer back, and saves it.
const LINES = [
  { who: "agent", text: "Hi Pak Wahyu, this is the AI assistant for Koperasi Sawit Maju. Is now a good time?" },
  { who: "farmer", text: "Yes, go ahead." },
  { who: "agent", text: "When is your next harvest, and about how much?" },
  { who: "farmer", text: "Around 1,600 kilos, on the 14th." },
  { who: "agent", text: "So 1,600 kg on Saturday 14 November. Is that right?" },
  { who: "farmer", text: "Yes, that's right." },
];

// The call as a timeline (seconds): ringing, then each line, then the saved card, then a pause.
const RING = 2.2, PER_LINE = 1.9, SAVED = 3.2;
const LOOP = RING + LINES.length * PER_LINE + SAVED;

export function startPhone(canvas, { still = false } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "low-power" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
  camera.position.set(0, 0, 11);

  scene.add(new THREE.HemisphereLight(0xeaf6ef, 0x0f3d2a, 1.2));
  const key = new THREE.DirectionalLight(0xffffff, 1.6);
  key.position.set(-3, 4, 6);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0x7fe0b4, 1.2);
  rim.position.set(4, -1, -3);
  scene.add(rim);

  const disposables = [];
  const keep = (x) => { disposables.push(x); return x; };

  // The phone: a rounded slab with a bevel, a screen in front, a small camera dot.
  const phone = new THREE.Group();
  const bw = 2.3, bh = 4.6, r = 0.36;
  const shape = new THREE.Shape();
  shape.moveTo(-bw / 2 + r, -bh / 2);
  shape.lineTo(bw / 2 - r, -bh / 2); shape.quadraticCurveTo(bw / 2, -bh / 2, bw / 2, -bh / 2 + r);
  shape.lineTo(bw / 2, bh / 2 - r); shape.quadraticCurveTo(bw / 2, bh / 2, bw / 2 - r, bh / 2);
  shape.lineTo(-bw / 2 + r, bh / 2); shape.quadraticCurveTo(-bw / 2, bh / 2, -bw / 2, bh / 2 - r);
  shape.lineTo(-bw / 2, -bh / 2 + r); shape.quadraticCurveTo(-bw / 2, -bh / 2, -bw / 2 + r, -bh / 2);
  const bodyGeo = keep(new THREE.ExtrudeGeometry(shape, { depth: 0.18, bevelEnabled: true, bevelThickness: 0.06, bevelSize: 0.06, bevelSegments: 4, curveSegments: 12 }));
  bodyGeo.translate(0, 0, -0.09);
  const body = new THREE.Mesh(bodyGeo, keep(new THREE.MeshStandardMaterial({ color: 0x1b2a23, metalness: 0.55, roughness: 0.35 })));
  phone.add(body);

  const screenCanvas = document.createElement("canvas");
  screenCanvas.width = W; screenCanvas.height = H;
  const ctx = screenCanvas.getContext("2d");
  const tex = keep(new THREE.CanvasTexture(screenCanvas));
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  const screen = new THREE.Mesh(keep(new THREE.PlaneGeometry(bw - 0.16, bh - 0.16)), keep(new THREE.MeshBasicMaterial({ map: tex, toneMapped: false })));
  screen.position.z = 0.16;
  phone.add(screen);
  const lens = new THREE.Mesh(keep(new THREE.CircleGeometry(0.045, 16)), keep(new THREE.MeshBasicMaterial({ color: 0x050807 })));
  lens.position.set(0, bh / 2 - 0.2, 0.17);
  phone.add(lens);
  scene.add(phone);

  // Sound: thin rings that spread out behind the phone while the call is on.
  const rings = [];
  const ringGeo = keep(new THREE.RingGeometry(1.0, 1.03, 64));
  for (let i = 0; i < 3; i++) {
    const m = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ color: 0x7fe0b4, transparent: true, opacity: 0, depthWrite: false }));
    m.position.z = -0.6;
    scene.add(m);
    rings.push({ m, offset: i / 3 });
  }

  // ---------- the screen ----------
  function roundRect(x, y, w, h, rad, fill) {
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, rad);
    ctx.fillStyle = fill;
    ctx.fill();
  }
  function wrap(text, maxW, font) {
    ctx.font = font;
    const words = text.split(" ");
    const out = [];
    let lineText = "";
    for (const w of words) {
      const t = lineText ? `${lineText} ${w}` : w;
      if (ctx.measureText(t).width > maxW && lineText) { out.push(lineText); lineText = w; } else lineText = t;
    }
    if (lineText) out.push(lineText);
    return out;
  }
  function header(status, live) {
    roundRect(0, 0, W, 210, 0, C.bar);
    ctx.fillStyle = C.mint;
    ctx.font = `700 22px ${FONT}`;
    ctx.fillText("AI agent · Koperasi Sawit Maju", 40, 64);
    ctx.fillStyle = C.text;
    ctx.font = `800 44px ${FONT}`;
    ctx.fillText("Pak Wahyu", 40, 124);
    ctx.fillStyle = live ? C.mint : C.sub;
    ctx.font = `600 26px ${FONT}`;
    ctx.fillText(status, 40, 170);
  }
  function draw(t) {
    const tt = ((t % LOOP) + LOOP) % LOOP;
    ctx.clearRect(0, 0, W, H);
    roundRect(0, 0, W, H, 0, C.bg);
    if (tt < RING) {
      header("Calling…", false);
      // The farmer's initials with a soft pulse, and three dots.
      const pulse = 1 + 0.06 * Math.sin(tt * 6);
      ctx.save();
      ctx.translate(W / 2, 520);
      ctx.scale(pulse, pulse);
      roundRect(-110, -110, 220, 220, 110, "#1F6B47");
      ctx.restore();
      ctx.fillStyle = C.text;
      ctx.font = `800 80px ${FONT}`;
      ctx.textAlign = "center";
      ctx.fillText("PW", W / 2, 548);
      ctx.font = `600 28px ${FONT}`;
      ctx.fillStyle = C.sub;
      ctx.fillText("Air Molek", W / 2, 700);
      ctx.textAlign = "left";
      for (let i = 0; i < 3; i++) {
        const on = Math.floor(tt * 3) % 3 === i;
        roundRect(W / 2 - 46 + i * 36, 760, 18, 18, 9, on ? C.mint : "#2C3A33");
      }
      return;
    }
    const callT = tt - RING;
    const secs = Math.floor(callT);
    header(`On the call · 00:${String(secs).padStart(2, "0")}`, true);
    const shown = Math.min(LINES.length, Math.floor(callT / PER_LINE) + 1);
    // Bubbles from the newest upwards, so the latest line is always in view.
    let y = H - 40;
    const saved = callT >= LINES.length * PER_LINE;
    if (saved) {
      const k = Math.min(1, (callT - LINES.length * PER_LINE) / 0.4);
      ctx.globalAlpha = k;
      roundRect(30, H - 250, W - 60, 210, 26, C.card);
      ctx.fillStyle = C.cardText;
      ctx.font = `800 30px ${FONT}`;
      ctx.fillText("✓  Added to the forecast", 60, H - 186);
      ctx.font = `700 40px ${FONT}`;
      ctx.fillText("1,600 kg on 14 Nov", 60, H - 128);
      ctx.font = `600 24px ${FONT}`;
      ctx.fillText("Confirmed by Pak Wahyu", 60, H - 82);
      ctx.globalAlpha = 1;
      y = H - 280;
    }
    for (let i = shown - 1; i >= 0 && y > 240; i--) {
      const l = LINES[i];
      const maxW = W - 130;
      const textLines = wrap(l.text, maxW, `700 36px ${FONT}`);
      const h = 30 + textLines.length * 46;
      const x = l.who === "agent" ? W - 30 - (maxW + 40) : 30;
      const appear = i === shown - 1 && !saved ? Math.min(1, ((callT % PER_LINE)) / 0.35) : 1;
      y -= h;
      ctx.globalAlpha = appear;
      roundRect(x, y + (1 - appear) * 20, maxW + 40, h, 24, l.who === "agent" ? C.agent : C.farmer);
      ctx.fillStyle = C.text;
      ctx.font = `700 36px ${FONT}`;
      textLines.forEach((s, j) => ctx.fillText(s, x + 20, y + 50 + j * 46 + (1 - appear) * 20));
      ctx.globalAlpha = 1;
      y -= 18;
    }
  }

  // ---------- sizing and the loop ----------
  function resize() {
    const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    // The phone fills about a third of the panel's height, centred in its upper part (between the logo and the
    // headline). The view is shifted, not the phone, so it stays centred in its own turn.
    const wide = w / h > 0.9; // the phone layout: a short, wide header strip
    camera.position.z = wide ? 14 : 22;
    camera.setViewOffset(w, h, 0, h * (wide ? 0.05 : 0.2), w, h);
    camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();

  let stopped = false;
  const fontsReady = document.fonts?.ready || Promise.resolve();

  if (still) {
    fontsReady.then(() => {
      if (stopped) return;
      draw(LOOP - 0.5);
      tex.needsUpdate = true;
      phone.rotation.set(0.08, -0.32, 0.02);
      renderer.render(scene, camera);
    });
    return () => { stopped = true; ro.disconnect(); disposables.forEach((d) => d.dispose()); rings.forEach((x) => x.m.material.dispose()); renderer.dispose(); };
  }

  const clock = new THREE.Clock();
  let raf = 0, visible = true, lastDraw = -1;
  function frame() {
    raf = requestAnimationFrame(frame);
    if (!visible) return;
    const t = clock.getElapsedTime();
    // A gentle float and sway.
    phone.position.y = Math.sin(t * 0.9) * 0.12;
    phone.rotation.set(0.08 + Math.sin(t * 0.7) * 0.03, -0.32 + Math.sin(t * 0.35) * 0.18, 0.02);
    // Redraw the screen about 15 times a second (enough for the clock and the fades).
    if (t - lastDraw > 1 / 15) { draw(t); tex.needsUpdate = true; lastDraw = t; }
    // Rings while the call is on (not while it is still ringing).
    const tt = t % LOOP;
    const talking = tt > RING && tt < LOOP - 1;
    for (const ring of rings) {
      const k = ((t * 0.45 + ring.offset) % 1);
      ring.m.scale.setScalar(1.3 + k * 2.2);
      ring.m.position.y = phone.position.y;
      ring.m.material.opacity = talking ? (1 - k) * 0.35 : Math.max(0, ring.m.material.opacity - 0.02);
    }
    renderer.render(scene, camera);
  }
  const onVisibility = () => { visible = document.visibilityState === "visible"; };
  document.addEventListener("visibilitychange", onVisibility);
  fontsReady.then(() => { if (!stopped) frame(); });

  return () => {
    stopped = true;
    cancelAnimationFrame(raf);
    document.removeEventListener("visibilitychange", onVisibility);
    ro.disconnect();
    disposables.forEach((d) => d.dispose());
    rings.forEach((x) => x.m.material.dispose());
    renderer.dispose();
  };
}
