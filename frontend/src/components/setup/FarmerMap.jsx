import { useEffect, useMemo, useRef, useState } from "react";
import { cfg } from "../../lib.js";
import { crmOf, STAGES } from "../../crm.js";
import { SegToggle } from "../../ui.jsx";

// The campaign's farmer plots on a map, coloured by stage (to call, answered, deal...) or by certification, for the
// traceability story. With a Google Maps browser key (MAPS_API_KEY, written into config.js by the deploy) it is a
// Google map; without one, the same dots on a plain drawn map, so the page never depends on the key.
const STAGE_COLOR = { to_call: "#E3A72F", calling: "#3C8FD0", no_reply: "#C2410C", answered: "#16774E", offer: "#8A5605", deal: "#0F3D2A", delivered: "#6B7280" };
const CERT_COLOR = { ISPO: "#16774E", RSPO: "#3C8FD0", none: "#B9B8AF" };

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
  const box = useRef(null);
  const crm = useMemo(() => crmOf(state, cid), [state, cid]);
  const points = crm.farmers.filter((x) => x.farmer.plot_lat != null && x.farmer.plot_lng != null).map((x) => ({
    f: x.farmer, lat: Number(x.farmer.plot_lat), lng: Number(x.farmer.plot_lng),
    color: by === "stage" ? STAGE_COLOR[x.stage] : CERT_COLOR[(x.farmer.certification || "").toUpperCase().includes("RSPO") ? "RSPO" : (x.farmer.certification || "").toUpperCase().includes("ISPO") ? "ISPO" : "none"],
    label: by === "stage" ? STAGES.find((s) => s.key === x.stage)?.label : (x.farmer.certification || "Not certified"),
  }));
  const key = cfg.mapsKey;
  const google = key && !failed;

  useEffect(() => {
    const refused = () => setFailed(true);
    refusedListeners.add(refused);
    return () => refusedListeners.delete(refused);
  }, []);

  useEffect(() => {
    if (!google || !box.current || !points.length) return undefined;
    let markers = [];
    let alive = true;
    loadMaps(key).then((maps) => {
      if (!alive || !box.current) return;
      const bounds = new maps.LatLngBounds();
      points.forEach((p) => bounds.extend({ lat: p.lat, lng: p.lng }));
      const map = new maps.Map(box.current, { mapTypeId: "hybrid", disableDefaultUI: true, zoomControl: true, gestureHandling: "cooperative" });
      map.fitBounds(bounds, 24);
      markers = points.map((p) => {
        const m = new maps.Marker({ map, position: { lat: p.lat, lng: p.lng }, title: `${p.f.name}: ${p.label}`,
          icon: { path: maps.SymbolPath.CIRCLE, scale: 6, fillColor: p.color, fillOpacity: 1, strokeColor: "#fff", strokeWeight: 1.5 } });
        m.addListener("click", () => onOpen?.(p.f));
        return m;
      });
    }).catch(() => setFailed(true));
    return () => { alive = false; markers.forEach((m) => m.setMap(null)); };
  }, [google, key, by, points.length, cid]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!points.length) return null;
  const lats = points.map((p) => p.lat), lngs = points.map((p) => p.lng);
  const [minLat, maxLat, minLng, maxLng] = [Math.min(...lats), Math.max(...lats), Math.min(...lngs), Math.max(...lngs)];
  const W = 640, H = 300, pad = 18;
  const x = (lng) => pad + ((lng - minLng) / ((maxLng - minLng) || 1)) * (W - 2 * pad);
  const y = (lat) => H - pad - ((lat - minLat) / ((maxLat - minLat) || 1)) * (H - 2 * pad);
  const legend = by === "stage" ? STAGES.filter((s) => points.some((p) => p.label === s.label)).map((s) => [s.label, STAGE_COLOR[s.key]])
    : [["ISPO", CERT_COLOR.ISPO], ["RSPO", CERT_COLOR.RSPO], ["Not certified", CERT_COLOR.none]];
  return (
    <section className="card map-card" aria-labelledby="map-title">
      <div className="card-head">
        <div><h2 id="map-title">Plots on the map</h2><span className="sub">{points.length} of {crm.farmers.length} farmers have a mapped plot. Click a plot to open the farmer.</span></div>
        <SegToggle label="Colour by" options={[["stage", "Stage"], ["cert", "Certification"]]} value={by} onChange={setBy} />
      </div>
      {google ? <div ref={box} className="gmap" role="region" aria-label="Map of farmer plots" />
        : (
          <svg className="plot-map" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Map of ${points.length} farmer plots`}>
            <rect x="0" y="0" width={W} height={H} rx="10" fill="#EEF3EC" />
            {[0.25, 0.5, 0.75].map((t) => <line key={t} x1={pad} x2={W - pad} y1={pad + t * (H - 2 * pad)} y2={pad + t * (H - 2 * pad)} stroke="#DCE5DA" />)}
            {points.map((p) => (
              <circle key={p.f.id} cx={x(p.lng)} cy={y(p.lat)} r="5" fill={p.color} stroke="#fff" strokeWidth="1.5" style={{ cursor: "pointer" }} onClick={() => onOpen?.(p.f)}>
                <title>{`${p.f.name}: ${p.label}`}</title>
              </circle>
            ))}
          </svg>
        )}
      <p className="map-legend small">{legend.map(([t, c]) => <span key={t}><i style={{ background: c }} />{t}</span>)}
        {!google && <span className="muted">{failed ? "Google Maps refused the key here (check the key's allowed websites); showing a plain map." : "Plain map: set MAPS_API_KEY to show satellite imagery."}</span>}</p>
    </section>
  );
}
