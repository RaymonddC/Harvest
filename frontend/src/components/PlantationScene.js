import * as THREE from "three";

// The sign-in page's picture: a palm plantation seen from above, the mill in the middle, and the agent's calls
// arcing out from the mill to the farms. A farm turns mint when its farmer answers; when every farm has answered
// they all fade back and the round starts again. Plain Three.js (one render loop, no other animation library),
// loaded only on this page.
//
// startPlantation(canvas, { still }) returns a stop() function that removes everything it added.
// still: draw one frame with some farms answered and no motion (the "reduce motion" setting).

const FOREST = 0x0f3d2a;
const GROUND = 0x15503a;
const TRUNK = 0x6b5a3e;
const FROND = 0x2e8b5c;
const FROND_DARK = 0x1f6b47;
const MINT = 0x7fe0b4;
const MILL = 0xeaf3ee;

export function startPlantation(canvas, { still = false } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "low-power" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(FOREST, 22, 40);
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);

  scene.add(new THREE.HemisphereLight(0xdff5ea, FOREST, 1.1));
  const sun = new THREE.DirectionalLight(0xfff4d6, 1.4);
  sun.position.set(6, 12, 4);
  scene.add(sun);

  const disposables = [];
  const keep = (x) => { disposables.push(x); return x; };

  // Ground: a gently uneven field.
  const groundGeo = keep(new THREE.PlaneGeometry(40, 40, 40, 40));
  const pos = groundGeo.attributes.position;
  for (let i = 0; i < pos.count; i++) {
    const x = pos.getX(i), y = pos.getY(i);
    pos.setZ(i, Math.sin(x * 0.35) * 0.18 + Math.cos(y * 0.28) * 0.15);
  }
  groundGeo.computeVertexNormals();
  const ground = new THREE.Mesh(groundGeo, keep(new THREE.MeshStandardMaterial({ color: GROUND, flatShading: true, roughness: 1 })));
  ground.rotation.x = -Math.PI / 2;
  scene.add(ground);

  // Farms: blocks of palms in rows around the mill, each with a marker that lights when its farmer answers.
  const rng = mulberry32(11);
  const farms = [];
  for (let ring = 0; ring < 3; ring++) {
    const count = [6, 9, 12][ring];
    const radius = [4.2, 7.4, 10.8][ring];
    for (let k = 0; k < count; k++) {
      const a = (k / count) * Math.PI * 2 + ring * 0.4 + (rng() - 0.5) * 0.25;
      const r = radius + (rng() - 0.5) * 0.9;
      farms.push({ x: Math.cos(a) * r, z: Math.sin(a) * r, rot: a, lit: 0, target: 0 });
    }
  }

  // Palms as instanced trunks and crowns (a few thousand triangles in all).
  const palms = [];
  for (const f of farms) {
    for (let i = 0; i < 3; i++) {
      for (let j = 0; j < 3; j++) {
        const lx = (i - 1) * 0.62 + (rng() - 0.5) * 0.12;
        const lz = (j - 1) * 0.62 + (rng() - 0.5) * 0.12;
        const c = Math.cos(f.rot), s = Math.sin(f.rot);
        palms.push({ x: f.x + lx * c - lz * s, z: f.z + lx * s + lz * c, h: 0.55 + rng() * 0.3, spin: rng() * Math.PI });
      }
    }
  }
  const trunkGeo = keep(new THREE.CylinderGeometry(0.035, 0.05, 1, 5));
  const crownGeo = keep(new THREE.ConeGeometry(0.34, 0.16, 7, 1));
  const trunks = new THREE.InstancedMesh(trunkGeo, keep(new THREE.MeshStandardMaterial({ color: TRUNK, flatShading: true })), palms.length);
  const crowns = new THREE.InstancedMesh(crownGeo, keep(new THREE.MeshStandardMaterial({ color: FROND, flatShading: true })), palms.length);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), sc = new THREE.Vector3(), p = new THREE.Vector3();
  const frond = new THREE.Color(FROND), frondDark = new THREE.Color(FROND_DARK);
  palms.forEach((t, i) => {
    m.compose(p.set(t.x, t.h / 2, t.z), q.identity(), sc.set(1, t.h, 1));
    trunks.setMatrixAt(i, m);
    q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), t.spin);
    m.compose(p.set(t.x, t.h + 0.04, t.z), q, sc.set(1, 1, 1));
    crowns.setMatrixAt(i, m);
    crowns.setColorAt(i, i % 3 ? frond : frondDark);
  });
  scene.add(trunks, crowns);

  // Farm markers: a flat disc under each block, dark until the farmer answers.
  const markerGeo = keep(new THREE.CircleGeometry(1.05, 24));
  const dark = new THREE.Color(0x1a5a41), mint = new THREE.Color(MINT);
  for (const f of farms) {
    const mat = keep(new THREE.MeshBasicMaterial({ color: dark.clone(), transparent: true, opacity: 0.55 }));
    f.marker = new THREE.Mesh(markerGeo, mat);
    f.marker.rotation.x = -Math.PI / 2;
    f.marker.position.set(f.x, 0.36, f.z);
    scene.add(f.marker);
  }

  // The mill: a low hall with a chimney, a little light on top.
  const millMat = keep(new THREE.MeshStandardMaterial({ color: MILL, flatShading: true, roughness: 0.7 }));
  const hall = new THREE.Mesh(keep(new THREE.BoxGeometry(1.6, 0.6, 1.1)), millMat);
  hall.position.set(0, 0.6, 0);
  const roof = new THREE.Mesh(keep(new THREE.CylinderGeometry(0.01, 0.95, 0.4, 4, 1)), keep(new THREE.MeshStandardMaterial({ color: 0x9cc3ae, flatShading: true })));
  roof.rotation.y = Math.PI / 4;
  roof.scale.set(1.2, 1, 0.85);
  roof.position.set(0, 1.1, 0);
  const chimney = new THREE.Mesh(keep(new THREE.CylinderGeometry(0.09, 0.11, 1.3, 8)), millMat);
  chimney.position.set(0.55, 1.25, -0.25);
  const beacon = new THREE.Mesh(keep(new THREE.SphereGeometry(0.09, 12, 8)), keep(new THREE.MeshBasicMaterial({ color: MINT })));
  beacon.position.set(0.55, 1.98, -0.25);
  scene.add(hall, roof, chimney, beacon);

  // Calls: an arc from the mill to a farm, drawn as it travels, then a ring on the farm when it is answered.
  const calls = [];
  const lineMat = keep(new THREE.LineBasicMaterial({ color: 0xb8f5d8, transparent: true, opacity: 1 }));
  const ringGeo = keep(new THREE.RingGeometry(0.9, 1.0, 32));
  const SEG = 48;
  function newCall(f) {
    const from = new THREE.Vector3(0.55, 2, -0.25), to = new THREE.Vector3(f.x, 0.4, f.z);
    const mid = from.clone().lerp(to, 0.5);
    mid.y += 0.8 + from.distanceTo(to) * 0.12;
    const curve = new THREE.QuadraticBezierCurve3(from, mid, to);
    const geo = new THREE.BufferGeometry().setFromPoints(curve.getPoints(SEG));
    geo.setDrawRange(0, 0);
    const line = new THREE.Line(geo, lineMat);
    const ring = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ color: MINT, transparent: true, opacity: 0, side: THREE.DoubleSide }));
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(f.x, 0.4, f.z);
    scene.add(line, ring);
    calls.push({ f, line, ring, geo, t: 0 });
  }
  function endCall(c) {
    scene.remove(c.line, c.ring);
    c.geo.dispose();
    c.ring.material.dispose();
  }

  // Sizing: follow the canvas's box.
  function resize() {
    const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    // Draw the mill in the upper part of the panel, clear of the words at the bottom.
    camera.setViewOffset(w, h, 0, h * (w / h > 1 ? 0.12 : 0.2), w, h);
    camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();

  let angle = 0.7;
  function placeCamera() {
    camera.position.set(Math.cos(angle) * 17, 15, Math.sin(angle) * 17);
    camera.lookAt(0, 0, 0);
  }

  function paintFarms(dt) {
    for (const f of farms) {
      f.lit += (f.target - f.lit) * Math.min(1, dt * 3);
      f.marker.material.color.copy(dark).lerp(mint, f.lit);
      f.marker.material.opacity = 0.55 + f.lit * 0.3;
    }
  }

  if (still) {
    farms.forEach((f, i) => { if (i % 3 === 0) { f.target = 1; f.lit = 1; } });
    placeCamera();
    paintFarms(1);
    renderer.render(scene, camera);
    return () => { ro.disconnect(); disposables.forEach((d) => d.dispose()); renderer.dispose(); };
  }

  const clock = new THREE.Clock();
  let raf = 0, nextCall = 0.6, queue = shuffled(farms, rng), visible = true;
  function frame() {
    raf = requestAnimationFrame(frame);
    if (!visible) return;
    const dt = Math.min(clock.getDelta(), 0.05);
    angle += dt * 0.035; // one turn in about three minutes
    placeCamera();
    beacon.material.color.setHSL(0.42, 0.6, 0.62 + Math.sin(clock.elapsedTime * 3) * 0.08);

    nextCall -= dt;
    if (nextCall <= 0 && calls.length < 3) {
      if (!queue.length) { // every farm answered: let them fade, then a new round
        farms.forEach((f) => { f.target = 0; });
        queue = shuffled(farms, rng);
        nextCall = 2.5;
      } else {
        newCall(queue.pop());
        nextCall = 0.9 + rng() * 0.9;
      }
    }
    for (let i = calls.length - 1; i >= 0; i--) {
      const c = calls[i];
      c.t += dt;
      const travel = Math.min(c.t / 1.1, 1);
      c.geo.setDrawRange(0, Math.floor(travel * (SEG + 1)));
      if (travel >= 1) {
        const r = c.t - 1.1; // answered: the ring spreads and the farm lights
        c.f.target = 1;
        c.ring.material.opacity = Math.max(0, 0.9 - r * 0.9);
        c.ring.scale.setScalar(1 + r * 1.2);
        c.line.visible = r < 0.8;
        if (r > 1) { endCall(c); calls.splice(i, 1); }
      }
    }
    paintFarms(dt);
    renderer.render(scene, camera);
  }
  const onVisibility = () => { visible = document.visibilityState === "visible"; clock.getDelta(); };
  document.addEventListener("visibilitychange", onVisibility);
  frame();

  return () => {
    cancelAnimationFrame(raf);
    document.removeEventListener("visibilitychange", onVisibility);
    ro.disconnect();
    calls.forEach(endCall);
    disposables.forEach((d) => d.dispose());
    trunks.dispose();
    crowns.dispose();
    renderer.dispose();
  };
}

function shuffled(list, rng) {
  const a = [...list];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

// A small seeded random generator, so the plantation looks the same on every visit.
function mulberry32(seed) {
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
