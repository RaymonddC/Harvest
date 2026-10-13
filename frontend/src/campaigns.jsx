import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { useLive } from "./live.jsx";

// Crops a mill can run a campaign for. The label is what planners read; the id matches
// farmers.crop, limits.id and (later) campaigns.crop.
export const CROPS = [
  { id: "palm", label: "Palm FFB" },
  { id: "rubber", label: "Rubber" },
  { id: "coffee", label: "Coffee" },
];
export const cropName = (id) => CROPS.find((c) => c.id === id)?.label || id;

/*
 * Multi-crop campaigns (task C-05). The screens are ready; the backend switches them on.
 *
 * Today the backend keeps one campaign (`campaigns/current`, no crop) for the configured crop.
 * When it sets `settings.multi_crop: true`, the app expects:
 *   - state.campaigns: [{ id, crop, kind, status, target_kg_per_week, weeks, started_at }]
 *   - state.forecast rows and state.offers carrying `crop`
 *   - POST /api/campaigns { crop, target_kg_per_week, weeks } -> the new campaign
 *   - POST /api/campaigns/{id}/start { kind } and POST /api/campaigns/{id}/stop
 * Until then "New campaign" and the other crops show as coming soon.
 */
export const multiCrop = (state) => !!state?.settings?.multi_crop;

// The campaigns, each with its crop, from either shape of the data.
export function campaignsOf(state) {
  if (!state) return [];
  const fallbackCrop = state.limits[0]?.crop || "palm";
  return state.campaigns.map((c) => ({
    ...c,
    crop: c.crop || fallbackCrop,
    target_kg_per_week: c.target_kg_per_week ?? state.settings?.target_kg_per_week,
    weeks: c.weeks ?? state.settings?.weeks,
  }));
}

// Rows for one crop. Records without a crop belong to the single crop of today's backend.
export const forCrop = (list, crop) => list.filter((x) => !x.crop || x.crop === crop);

const Crop = createContext({ crop: "palm", setCrop: () => {} });
const KEY = "harvestCrop";

// The crop the planner is looking at, shared by every page and remembered in this browser.
export function CropProvider({ children }) {
  const { state } = useLive();
  const [crop, setCropState] = useState(() => { try { return localStorage.getItem(KEY) || ""; } catch { return ""; } });
  const crops = useMemo(() => [...new Set(campaignsOf(state).map((c) => c.crop))], [state]);
  // Fall back to the first crop that has a campaign when the remembered one has none.
  useEffect(() => {
    if (crops.length && !crops.includes(crop)) setCropState(crops[0]);
  }, [crops, crop]);
  const setCrop = (id) => {
    setCropState(id);
    try { localStorage.setItem(KEY, id); } catch { /* storage blocked: the choice lasts this visit */ }
  };
  return <Crop.Provider value={{ crop: crop || crops[0] || "palm", setCrop }}>{children}</Crop.Provider>;
}

export const useCrop = () => useContext(Crop);
