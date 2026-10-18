import { useEffect, useMemo, useRef, useState } from "react";
import { api, can, cfg, fmtT } from "../../lib.js";
import { crmOf, STAGES } from "../../crm.js";
import { bandOf, decodePolyline, fmtMinutes, nearestMill, TIME_BANDS } from "../../mills.js";
import { useAct } from "../../toast.jsx";
import { ActButton, SegToggle } from "../../ui.jsx";

// The campaign's farmer plots and the mills (named squares) on a map. Clicking a plot draws the road from it to the
// farmer's nearest mill (Google's route, from the server: /api/farmers/{id}/mill-route) with the distance and truck time. Plots are coloured by stage (to call, answered, deal...), by
// certification (traceability) or by the truck time to their nearest mill (fresh fruit loses quality while it waits);
// under the map, each mill's catchment: how many farmers are nearest to it, their usual supply, and how far they are.
// With a Google Maps browser key (MAPS_API_KEY, in config.js) it is a Google map; without one, a plain drawing.
const STAGE_COLOR = { to_call: "#E3A72F", calling: "#3C8FD0", no_reply: "#C2410C", answered: "#16774E", offer: "#8A5605", deal: "#0F3D2A", delivered: "#6B7280" };
const CERT_COLOR = { ISPO: "#16774E", RSPO: "#3C8FD0", none: "#B9B8AF" };
const MILL_COLOR = "#0F3D2A";
const ROUTE_COLOR = "#3C8FD0";
const millShort = (name) => (name || "").replace(/^.*?mill,\s*/i, "") || name;
const certOf = (f) => { const c = (f.certification || "").toUpperCase(); return c.includes("RSPO") ? "RSPO" : c.includes("ISPO") ? "ISPO" : "none"; };

let mapsLoading = null;
let mapsRefused = false; // Google refused the key (e.g. this address is not in the key's allowed websites)
const refusedListeners = new Set();
function loadMaps(key) {
  if (window.google?.maps) return Promise.resolve(window.google.maps);
  if (!mapsLoading) {
    mapsLoading = new Promise((resolve, reject) => {
      const cb = `harvestMaps${Date.now()}`;
      window[cb] = () => resolve(window.google.maps);
      window.gm_authFailure = () => { mapsRefused = true; refusedListeners.forEach((f) => f()); };
      const s = document.createElement("script");
      s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(key)}&v=weekly&loading=async&callback=${cb}`;
      s.async = true;
      s.onerror = () => reject(new Error("Google Maps did not load"));
      document.head.appendChild(s);
    });
  }
  return mapsLoading;
}

export default function FarmerMap({ state, cid, onOpen }) {
  const [by, setBy] = useState("stage");
  const [failed, setFailed] = useState(mapsRefused);
  const [ready, setReady] = useState(null); // the Google maps namespace once the map exists
  const [form, setForm] = useState(null); // { id?, name, lat, lng } while adding or moving a mill
  const [placing, setPlacing] = useState(false);
  const [picked, setPicked] = useState(null); // { f, route?, error? } the plot whose road to the mill is shown
  const box = useRef(null);
  const mapRef = useRef(null);
  const fitted = useRef(false);
  const crm = useMemo(() => crmOf(state, cid), [state, cid]);
  const mills = state.mills || [];
  const points = crm.farmers.filter((x) => x.farmer.plot_lat != null && x.farmer.plot_lng != null).map((x) => {
    const near = nearestMill(mills, x.farmer);
    const band = near ? bandOf(near.minutes) : null;
    const color = by === "stage" ? STAGE_COLOR[x.stage] : by === "cert" ? CERT_COLOR[certOf(x.farmer)] : (band?.color || "#B9B8AF");
    const label = by === "stage" ? STAGES.find((s) => s.key === x.stage)?.label : by === "cert" ? (x.farmer.certification || "Not certified")
      : near ? `${fmtMinutes(near.minutes)} to ${near.mill.name}` : "No mill";
    return { f: x.farmer, lat: Number(x.farmer.plot_lat), lng: Number(x.farmer.plot_lng), color, label, near };
  });
  const key = cfg.mapsKey;
  const google = key && !failed;
  const hasAny = points.length > 0 || mills.length > 0;
  const sig = `${cid}|${by}|${points.length}|${mills.map((m) => `${m.id}:${m.lat},${m.lng},${m.name}`).join(";")}|${form ? `${form.lat},${form.lng}` : ""}|${picked?.f.id || ""}`;
  const routePath = picked?.route ? (picked.route.polyline ? decodePolyline(picked.route.polyline) : [picked.route.from, picked.route.to]) : null;

  const pick = (f) => {
    if (picked?.f.id === f.id) return;
    setPicked({ f });
    api(`/api/farmers/${f.id}/mill-route`, { method: "GET" })
      .then((route) => setPicked((cur) => (cur?.f.id === f.id ? { f, route } : cur)))
      .catch((e) => setPicked((cur) => (cur?.f.id === f.id ? { f, error: e.message || "No route" } : cur)));
  };

  useEffect(() => {
    const refused = () => setFailed(true);
    refusedListeners.add(refused);
    return () => refusedListeners.delete(refused);
  }, []);

  // The map itself, once.
  useEffect(() => {
    if (!google || !box.current) return undefined;
    let alive = true;
    loadMaps(key).then((maps) => {
      if (!alive || !box.current) return;
      mapRef.current = new maps.Map(box.current, { mapTypeId: "hybrid", disableDefaultUI: true, zoomControl: true, gestureHandling: "cooperative" });
      fitted.current = false;
      setReady(maps);
    }).catch(() => setFailed(true));
    return () => { alive = false; };
  }, [google, key, hasAny]);

  // The plots and the mills on it.
  useEffect(() => {
    const maps = google ? ready : null, map = mapRef.current;
    if (!maps || !map) return undefined;
    if (!fitted.current && hasAny) {
      const bounds = new maps.LatLngBounds();
      points.forEach((p) => bounds.extend({ lat: p.lat, lng: p.lng }));
      mills.forEach((m) => bounds.extend({ lat: Number(m.lat), lng: Number(m.lng) }));
      map.fitBounds(bounds, 24);
      fitted.current = true;
    }
    const marks = points.map((p) => {
      const m = new maps.Marker({ map, position: { lat: p.lat, lng: p.lng }, title: `${p.f.name}: ${p.label}`,
        icon: { path: maps.SymbolPath.CIRCLE, scale: 6, fillColor: p.color, fillOpacity: 1, strokeColor: "#fff", strokeWeight: 1.5 } });
      m.addListener("click", () => pick(p.f));
      return m;
    });
    const square = "M -7,-7 7,-7 7,7 -7,7 z";
    mills.forEach((ml) => marks.push(new maps.Marker({ map, position: { lat: Number(ml.lat), lng: Number(ml.lng) }, title: ml.name, zIndex: 1000,
      label: { text: millShort(ml.name), color: "#fff", fontSize: "13px", fontWeight: "700", className: "gmill-label" },
      icon: { path: square, scale: 1.5, fillColor: MILL_COLOR, fillOpacity: 1, strokeColor: "#fff", strokeWeight: 3, labelOrigin: new maps.Point(0, 19) } })));
    const sel = picked && points.find((p) => p.f.id === picked.f.id);
    if (sel) {
      marks.push(new maps.Marker({ map, position: { lat: sel.lat, lng: sel.lng }, title: sel.f.name, zIndex: 999,
        icon: { path: maps.SymbolPath.CIRCLE, scale: 10, fillColor: sel.color, fillOpacity: 1, strokeColor: "#fff", strokeWeight: 3 } }));
    }
    if (form && form.lat !== "" && form.lng !== "" && !Number.isNaN(Number(form.lat)) && !Number.isNaN(Number(form.lng))) {
      marks.push(new maps.Marker({ map, position: { lat: Number(form.lat), lng: Number(form.lng) }, title: "New place", zIndex: 1001,
        icon: { path: square, scale: 1.1, fillColor: "#E3A72F", fillOpacity: 1, strokeColor: "#fff", strokeWeight: 2.5 } }));
    }
    return () => marks.forEach((m) => m?.setMap?.(null));
  }, [ready, sig, google]); // eslint-disable-line react-hooks/exhaustive-deps

  // The road from the picked plot to its mill.
  useEffect(() => {
    const maps = google ? ready : null, map = mapRef.current;
    if (!maps || !map || !routePath) return undefined;
    const path = routePath.map(([lat, lng]) => ({ lat, lng }));
    const byRoad = !!picked.route.polyline;
    const casing = new maps.Polyline({ map, path, strokeColor: "#fff", strokeOpacity: 0.9, strokeWeight: byRoad ? 8 : 6, zIndex: 900 });
    const line = new maps.Polyline({ map, path, strokeColor: ROUTE_COLOR, strokeOpacity: byRoad ? 1 : 0, strokeWeight: 5, zIndex: 901,
      icons: byRoad ? [] : [{ icon: { path: "M 0,-1 0,1", strokeOpacity: 1, strokeColor: ROUTE_COLOR, scale: 4 }, offset: "0", repeat: "14px" }] });
    const bounds = new maps.LatLngBounds();
    path.forEach((pt) => bounds.extend(pt));
    map.fitBounds(bounds, 60);
    return () => { casing.setMap(null); line.setMap(null); };
  }, [ready, google, picked?.route]); // eslint-disable-line react-hooks/exhaustive-deps

  // Click the map to place a mill.
  useEffect(() => {
    const map = mapRef.current;
    if (!google || !ready || !map || !placing) return undefined;
    map.setOptions({ draggableCursor: "crosshair" });
    const l = map.addListener("click", (e) => { setForm((f) => ({ ...f, lat: e.latLng.lat().toFixed(5), lng: e.latLng.lng().toFixed(5) })); setPlacing(false); });
    return () => { l?.remove?.(); map.setOptions?.({ draggableCursor: null }); };
  }, [ready, placing, google]);

  if (!hasAny) {
    return (
      <section className="card map-card" aria-labelledby="map-title">
        <div className="card-head"><div><h2 id="map-title">Plots and mills</h2>
          <span className="sub">None of the {crm.farmers.length} farmers has a plot location yet.</span></div></div>
        <p className="small muted" style={{ margin: 0 }}>Add a plot’s latitude and longitude on the farmer’s form (Edit), or in the CSV upload
          (columns plot_lat and plot_lng). Each farmer with a location shows here, with the truck time to the nearest mill.</p>
      </section>
    );
  }

  // The plain drawing: the plots and mills in their bounding box.
  const all = [...points.map((p) => [p.lat, p.lng]), ...mills.map((m) => [Number(m.lat), Number(m.lng)])];
  const lats = all.map((a) => a[0]), lngs = all.map((a) => a[1]);
  const [minLat, maxLat, minLng, maxLng] = [Math.min(...lats), Math.max(...lats), Math.min(...lngs), Math.max(...lngs)];
  const W = 640, H = 300, pad = 18;
  const x = (lng) => pad + ((lng - minLng) / ((maxLng - minLng) || 1)) * (W - 2 * pad);
  const y = (lat) => H - pad - ((lat - minLat) / ((maxLat - minLat) || 1)) * (H - 2 * pad);
  const svgClick = (e) => {
    if (!placing) return;
    const r = e.currentTarget.getBoundingClientRect();
    const sx = ((e.clientX - r.left) / r.width) * W, sy = ((e.clientY - r.top) / r.height) * H;
    const lng = minLng + ((sx - pad) / (W - 2 * pad)) * ((maxLng - minLng) || 1);
    const lat = minLat + ((H - pad - sy) / (H - 2 * pad)) * ((maxLat - minLat) || 1);
    setForm((f) => ({ ...f, lat: lat.toFixed(5), lng: lng.toFixed(5) }));
    setPlacing(false);
  };
  const legend = by === "stage" ? STAGES.filter((s) => points.some((p) => p.label === s.label)).map((s) => [s.label, STAGE_COLOR[s.key]])
    : by === "cert" ? [["ISPO", CERT_COLOR.ISPO], ["RSPO", CERT_COLOR.RSPO], ["Not certified", CERT_COLOR.none]]
      : TIME_BANDS.map((b) => [b.label, b.color]);
  const far = points.filter((p) => p.near?.far).length;
  return (
    <section className="card map-card" aria-labelledby="map-title">
      <div className="card-head">
        <div><h2 id="map-title">Plots and mills</h2>
          <span className="sub">{points.length} of {crm.farmers.length} farmers have a mapped plot{mills.length ? `; each is matched to the nearest of ${mills.length} mill${mills.length > 1 ? "s" : ""}` : ""}. Click a plot to see its road to the mill.</span></div>
        <SegToggle label="Colour by" options={[["stage", "Stage"], ["cert", "Certification"], ["time", "Truck time"]]} value={by} onChange={setBy} />
      </div>
      {placing && <p className="map-hint small" role="status">Click the map where the mill is.</p>}
      {picked && (
        <div className="route-card" role="status">
          <div>
            <b>{picked.f.name}</b>
            {picked.route ? (
              <span>to {picked.route.mill_name}: {Math.round(picked.route.road_km)} km by road, {fmtMinutes(picked.route.minutes)} by truck
                {picked.route.by_road ? "" : " (no road Google can find; straight line, estimated)"}{picked.route.far ? ". Far: fruit may lose quality on the way" : ""}</span>
            ) : picked.error ? <span className="muted">{picked.error}</span> : <span className="muted">Finding the road to the mill…</span>}
          </div>
          <button type="button" className="btn sm" onClick={() => onOpen?.(picked.f)}>Open farmer</button>
          <button type="button" className="btn sm ghost" aria-label="Clear the route" onClick={() => setPicked(null)}>Clear</button>
        </div>
      )}
      {google ? <div ref={box} className="gmap" role="region" aria-label="Map of farmer plots and mills" />
        : (
          <svg className={`plot-map ${placing ? "placing" : ""}`} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Map of ${points.length} farmer plots and ${mills.length} mills`} onClick={svgClick}>
            <rect x="0" y="0" width={W} height={H} rx="10" fill="#EEF3EC" />
            {[0.25, 0.5, 0.75].map((t) => <line key={t} x1={pad} x2={W - pad} y1={pad + t * (H - 2 * pad)} y2={pad + t * (H - 2 * pad)} stroke="#DCE5DA" />)}
            {points.map((p) => (
              <circle key={p.f.id} cx={x(p.lng)} cy={y(p.lat)} r="5" fill={p.color} stroke="#fff" strokeWidth="1.5" style={{ cursor: "pointer" }} onClick={(e) => { if (!placing) { e.stopPropagation(); pick(p.f); } }}>
                <title>{`${p.f.name}: ${p.label}`}</title>
              </circle>
            ))}
            {routePath && <polyline points={routePath.map(([la, lo]) => `${x(lo)},${y(la)}`).join(" ")} fill="none" stroke={ROUTE_COLOR} strokeWidth="3.5"
              strokeLinejoin="round" strokeDasharray={picked.route.polyline ? undefined : "6 5"} />}
            {mills.map((m) => (
              <g key={m.id}>
                <rect x={x(Number(m.lng)) - 8} y={y(Number(m.lat)) - 8} width="16" height="16" rx="2" fill={MILL_COLOR} stroke="#fff" strokeWidth="2.5"><title>{m.name}</title></rect>
                <text x={x(Number(m.lng))} y={y(Number(m.lat)) + 22} textAnchor="middle" className="svg-mill-label">{millShort(m.name)}</text>
              </g>
            ))}
            {form && form.lat !== "" && form.lng !== "" && <rect x={x(Number(form.lng)) - 7} y={y(Number(form.lat)) - 7} width="14" height="14" rx="2" fill="#E3A72F" stroke="#fff" strokeWidth="2.5" />}
          </svg>
        )}
      <p className="map-legend small">
        {legend.map(([t, c]) => <span key={t}><i style={{ background: c }} />{t}</span>)}
        {mills.length > 0 && <span><i className="sq" style={{ background: MILL_COLOR }} />Mill</span>}
        {!google && <span className="muted">{failed ? "Google Maps refused the key here (check the key’s allowed websites); showing a plain map." : "Plain map: set MAPS_API_KEY to show satellite imagery."}</span>}
      </p>
      <Mills state={state} points={points} far={far} form={form} setForm={setForm} placing={placing} setPlacing={setPlacing} />
    </section>
  );
}

// Each mill's catchment, and adding, moving or removing a mill.
function Mills({ state, points, far, form, setForm, placing, setPlacing }) {
  const act = useAct();
  const mills = state.mills || [];
  const edit = can("farmers.manage");
  const routed = points.filter((p) => p.near?.byRoad).length;
  const rows = mills.map((m) => {
    const mine = points.filter((p) => p.near?.mill.id === m.id);
    return { m, n: mine.length, kg: mine.reduce((s, p) => s + Number(p.f.usual_kg_week || 0), 0),
      avg: mine.length ? Math.round(mine.reduce((s, p) => s + p.near.minutes, 0) / mine.length) : null,
      max: mine.reduce((s, p) => Math.max(s, p.near.minutes), 0), far: mine.filter((p) => p.near.far).length };
  });
  const save = async () => {
    const body = { name: form.name, lat: Number(form.lat), lng: Number(form.lng) };
    const r = await act(() => api(form.id ? `/api/mills/${form.id}` : "/api/mills", { method: form.id ? "PUT" : "POST", body }),
      form.id ? `${form.name} moved.` : `${form.name} added. Each plot now goes to its nearest mill.`);
    if (r) { setForm(null); setPlacing(false); }
  };
  return (
    <div className="mills">
      <div className="mills-head">
        <h3>Mills</h3>
        {far > 0 && <span className="pill red">{far} plot{far > 1 ? "s" : ""} over 2 h from a mill</span>}
        {edit && !form && <button type="button" className="btn sm" onClick={() => setForm({ name: "", lat: "", lng: "" })}>Add a mill</button>}
      </div>
      {mills.length > 0 && points.length > 0 && (
        <p className="small muted routes-line" style={{ margin: 0 }}>
          {routed === points.length ? `Road distance and driving time from Google for all ${points.length} plots.`
            : `Road distance from Google for ${routed} of ${points.length} plots; the rest are estimated (no route found yet, or a plot or mill moved).`}
          {edit && routed < points.length && (
            <ActButton className="btn sm ghost" busy="Asking Google…" run={() => act(() => api("/api/mills/routes", { body: {} }),
              (r) => (r.updated ? `Road routes for ${r.updated} plots${r.no_road ? `; ${r.no_road} have no road Google can find` : ""}.` : "Already up to date."))}>Get road times</ActButton>
          )}
        </p>
      )}
      {mills.length ? (
        <table className="mills-table">
          <thead><tr><th>Mill</th><th className="r">Farmers nearest</th><th className="r">Usual supply</th><th className="r">Average truck time</th><th className="r">Longest</th>{edit && <th aria-label="Actions" />}</tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.m.id}>
                <td><b>{r.m.name}</b></td>
                <td className="r num">{r.n}</td>
                <td className="r num">{fmtT(r.kg)} t a week</td>
                <td className="r num">{r.avg != null ? fmtMinutes(r.avg) : "–"}</td>
                <td className={`r num ${r.far ? "warn" : ""}`}>{r.n ? fmtMinutes(r.max) : "–"}</td>
                {edit && (
                  <td className="r actions">
                    <button type="button" className="btn sm ghost" onClick={() => setForm({ id: r.m.id, name: r.m.name, lat: String(r.m.lat), lng: String(r.m.lng) })}>Move</button>
                    <ActButton className="btn sm ghost" busy="Removing…" run={() => act(() => api(`/api/mills/${r.m.id}`, { method: "DELETE" }), `${r.m.name} removed.`)}>Remove</ActButton>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="small muted" style={{ margin: 0 }}>No mill yet. Add one to see each plot’s nearest mill and truck time.</p>}
      <p className="small muted" style={{ margin: 0 }}>Truck time is Google’s driving time plus 30% for a loaded truck; an estimated one is the straight line plus 30% for winding roads, at 30 km/h. The purchase order and the confirmation call name each farmer’s nearest mill.</p>
      {form && (
        <div className="mill-form">
          <input aria-label="Mill name" placeholder="Mill name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <input aria-label="Latitude" placeholder="Latitude" inputMode="decimal" value={form.lat} onChange={(e) => setForm({ ...form, lat: e.target.value })} />
          <input aria-label="Longitude" placeholder="Longitude" inputMode="decimal" value={form.lng} onChange={(e) => setForm({ ...form, lng: e.target.value })} />
          <button type="button" className={`btn sm ${placing ? "solid" : ""}`} onClick={() => setPlacing(!placing)}>{placing ? "Click the map…" : "Pick on the map"}</button>
          <ActButton className="btn sm solid" busy="Saving…" disabled={!form.name.trim() || form.lat === "" || form.lng === ""} run={save}>{form.id ? "Save" : "Add mill"}</ActButton>
          <button type="button" className="btn sm ghost" onClick={() => { setForm(null); setPlacing(false); }}>Cancel</button>
        </div>
      )}
    </div>
  );
}
