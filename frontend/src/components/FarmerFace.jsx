// A small drawn portrait of a farmer, the same every time for the same person (picked from their id and name), so a
// board of farmers reads as people rather than initials. Women ("Bu ...") mostly wear a hijab; men ("Pak ...") a peci,
// a caping (the conical field hat) or nothing. Flat shapes in the app's earthy palette; decorative (aria-hidden).

const SKIN = ["#8D5A3B", "#A36B45", "#B97C52", "#C68E62", "#7A4B30", "#D29E74"];
const HIJAB = ["#2F6B4F", "#8C3B3B", "#3B4F8C", "#B5832C", "#6B4C8C", "#2E7D7A", "#A0522D"];
const SHIRT = ["#1F5F46", "#7A5230", "#35507A", "#9A3D2E", "#5D6B2F", "#4A4A6A"];
const HAIR = "#2A1E17";

function hash(s = "") {
  return [...s].reduce((h, c) => (Math.imul(h, 31) + c.charCodeAt(0)) >>> 0, 2166136261);
}

export function looksOf(name = "", id = "") {
  const h = hash(`${id}|${name}`);
  const pick = (arr, shift) => arr[(h >>> shift) % arr.length];
  const title = name.trim().split(/\s+/)[0]?.toLowerCase().replace(/\.$/, "");
  const woman = ["bu", "ibu", "mrs", "ms"].includes(title) || (!["pak", "bapak", "mr"].includes(title) && (h & 1) === 1);
  const headwear = woman ? ((h >>> 3) % 5 === 0 ? "hair" : "hijab") : ["peci", "caping", "bare", "peci"][(h >>> 3) % 4];
  return { woman, headwear, skin: pick(SKIN, 5), cloth: pick(HIJAB, 9), shirt: pick(SHIRT, 13) };
}

export default function FarmerFace({ name, id, size = 36, className = "" }) {
  const l = looksOf(name, id);
  return (
    <svg className={`farmer-face ${className}`.trim()} width={size} height={size} viewBox="0 0 40 40" aria-hidden="true" focusable="false">
      <rect width="40" height="40" rx="12" fill="#EFE8DA" />
      {/* shoulders */}
      <path d="M6 40c1.5-8 7-11.5 14-11.5S32.5 32 34 40Z" fill={l.headwear === "hijab" ? l.cloth : l.shirt} />
      {l.headwear === "hijab" ? (
        <>
          {/* the hijab frames the face and falls over the shoulders */}
          <path d="M9 22c0-7.5 4.8-12.5 11-12.5S31 14.5 31 22c0 4-1.2 6.6-3 8.5H12c-1.8-1.9-3-4.5-3-8.5Z" fill={l.cloth} />
          <ellipse cx="20" cy="21.5" rx="6.2" ry="7" fill={l.skin} />
          <path d="M13.6 18.5c1.4-3.6 3.6-5 6.4-5s5 1.4 6.4 5c-2-1.3-4-1.8-6.4-1.8s-4.4.5-6.4 1.8Z" fill={l.cloth} opacity=".55" />
        </>
      ) : (
        <>
          <rect x="17" y="25" width="6" height="5" fill={l.skin} />
          <ellipse cx="20" cy="20" rx="6.4" ry="7.2" fill={l.skin} />
          {l.headwear === "hair" && <path d="M12.8 20c-.6-6.4 3-10 7.2-10s7.8 3.6 7.2 10c-1-3.2-3.2-5-7.2-5.2-4 .2-6.2 2-7.2 5.2Z" fill={HAIR} />}
          {l.headwear === "bare" && <path d="M13.6 17.4c.6-4.4 3.2-6.4 6.4-6.4s5.8 2 6.4 6.4c-1.8-1.6-3.8-2.2-6.4-2.2s-4.6.6-6.4 2.2Z" fill={HAIR} />}
          {l.headwear === "peci" && <path d="M13.4 15.2c0-2.6 3-4 6.6-4s6.6 1.4 6.6 4v1.4H13.4Z" fill="#1E1E24" />}
          {l.headwear === "caping" && (
            <>
              <path d="M4.5 16.4 20 6.5l15.5 9.9c-4 1.6-9.2 2.3-15.5 2.3S8.5 18 4.5 16.4Z" fill="#D7B46A" />
              <path d="M20 6.5 13 15.6M20 6.5l7 9.1M20 6.5v11.9" stroke="#B8924A" strokeWidth=".8" />
            </>
          )}
        </>
      )}
      {/* eyes and a small smile */}
      <circle cx="17.6" cy={l.headwear === "hijab" ? 21.4 : 20.2} r=".9" fill="#2A1E17" />
      <circle cx="22.4" cy={l.headwear === "hijab" ? 21.4 : 20.2} r=".9" fill="#2A1E17" />
      <path d={l.headwear === "hijab" ? "M18.3 24.6q1.7 1.2 3.4 0" : "M18.3 23.6q1.7 1.2 3.4 0"} stroke="#2A1E17" strokeWidth=".9" fill="none" strokeLinecap="round" />
    </svg>
  );
}
