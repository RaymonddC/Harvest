// The nearest mill to a farmer's plot and the truck time to it. The same sums as backend/app/mills.py: keep in step.
//   road km = straight line x 1.3 (rural roads wind), minutes = road km at 30 km/h (a loaded truck), far = over 2 h
// (fresh fruit loses oil quality while it waits, so the time to the mill matters).
export const ROAD_FACTOR = 1.3;
export const TRUCK_KMH = 30;
export const FAR_MINUTES = 120;

export function kmBetween(lat1, lng1, lat2, lng2) {
  const r = 6371, rad = (d) => (d * Math.PI) / 180;
  const dp = rad(lat2 - lat1), dl = rad(lng2 - lng1);
  const a = Math.sin(dp / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dl / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(a));
}

export function nearestMill(mills, f) {
  if (!f || f.plot_lat == null || f.plot_lng == null || !mills?.length) return null;
  let best = null;
  for (const m of mills) {
    if (m.lat == null || m.lng == null) continue;
    const km = kmBetween(Number(f.plot_lat), Number(f.plot_lng), Number(m.lat), Number(m.lng));
    if (!best || km < best.km) best = { km, mill: m };
  }
  if (!best) return null;
  const road = best.km * ROAD_FACTOR;
  const minutes = Math.round((road / TRUCK_KMH) * 60);
  return { mill: best.mill, km: best.km, roadKm: road, minutes, far: minutes > FAR_MINUTES };
}

export const fmtMinutes = (m) => (m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} min`);
export const travelText = (n) => (n ? `${n.mill.name}, about ${Math.round(n.roadKm)} km by road, ${fmtMinutes(n.minutes)} by truck` : "");

// Truck-time bands for the map colours.
export const TIME_BANDS = [
  { key: "near", label: "Under 1 h", max: 60, color: "#16774E" },
  { key: "mid", label: "1 to 2 h", max: FAR_MINUTES, color: "#E3A72F" },
  { key: "far", label: "Over 2 h: fruit may lose quality", max: Infinity, color: "#C2410C" },
];
export const bandOf = (minutes) => TIME_BANDS.find((b) => minutes <= b.max);
