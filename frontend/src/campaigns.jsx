import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useLive } from "./live.jsx";

// Crops a mill can run a campaign for. The label is what planners read; the id matches
// farmers.crop, limits.id and campaigns.crop.
export const CROPS = [
  { id: "palm", label: "Palm FFB" },
  { id: "rubber", label: "Rubber" },
  { id: "coffee", label: "Coffee" },
];
export const cropName = (id) => CROPS.find((c) => c.id === id)?.label || id;

/*
 * Campaigns. Each has a crop, a weekly target, weeks to plan and its own farmers; a crop can have several.
 * A farmer is in at most one campaign (farmer.campaign_id; null = in the farmer database only). Farmers saved
 * before campaigns had their own lists have no campaign_id at all and belong to their crop's first campaign.
 * Harvests, offers and calls belong to the campaign in their own campaign_id, else to their farmer's.
 * The backend (services.farmer_campaign, doc_campaign) uses the same rules; keep the two in step.
 */
export const multiCrop = (state) => !!state?.settings?.multi_crop;

// The campaigns, each with its crop and a label: its name, else the crop.
export function campaignsOf(state) {
  if (!state) return [];
  const fallbackCrop = state.limits[0]?.crop || "palm";
  return state.campaigns.map((c) => {
    const crop = c.crop || fallbackCrop;
    return {
      ...c,
      crop,
      label: c.name || cropName(crop),
      target_kg_per_week: c.target_kg_per_week ?? state.settings?.target_kg_per_week,
      weeks: c.weeks ?? state.settings?.weeks,
    };
  }).sort((a, b) => (a.id === "current" ? -1 : b.id === "current" ? 1 : (a.created_at || "").localeCompare(b.created_at || "")));
}

// A crop's first campaign: the one with the crop's original id ("current" for the default crop), else the oldest.
export function firstOfCrop(camps, crop) {
  const mine = camps.filter((c) => c.crop === crop);
  return (mine.find((c) => c.id === "current" || c.id === crop) || mine[0])?.id || null;
}

export function farmerCampaign(farmer, camps) {
  if (farmer && "campaign_id" in farmer) return farmer.campaign_id || null;
  return farmer ? firstOfCrop(camps, farmer.crop || camps[0]?.crop) : null;
}

// Which campaign each record belongs to, worked out once per state.
export function useMembership(state) {
  return useMemo(() => {
    const camps = campaignsOf(state);
    const farmers = new Map((state?.farmers || []).map((f) => [f.id, f]));
    const of = (doc) => {
      if (doc.campaign_id) return doc.campaign_id;
      const f = farmers.get(doc.farmer_id);
      if (f) return farmerCampaign(f, camps);
      return firstOfCrop(camps, doc.crop || camps[0]?.crop);
    };
    return { camps, of, ofFarmer: (f) => farmerCampaign(f, camps) };
  }, [state]);
}

// The records of one campaign. Forecast rows carry campaign_id; farmers, calls and offers follow the rules above.
export function inCampaign(state, list, cid) {
  if (!state || !list) return [];
  const camps = campaignsOf(state);
  const farmers = new Map(state.farmers.map((f) => [f.id, f]));
  return list.filter((doc) => {
    if ("phone" in doc && "language" in doc) return farmerCampaign(doc, camps) === cid; // a farmer
    if (doc.campaign_id) return doc.campaign_id === cid;
    const f = farmers.get(doc.farmer_id);
    if (f) return farmerCampaign(f, camps) === cid;
    return firstOfCrop(camps, doc.crop || camps[0]?.crop) === cid;
  });
}

// The campaign by id, or a crop's first campaign, or an empty object.
export function campaignFor(state, ref) {
  const camps = campaignsOf(state);
  return camps.find((c) => c.id === ref) || camps.find((c) => c.id === firstOfCrop(camps, ref)) || {};
}

// Rows for one crop (price limits and rival quotes belong to a crop, not to a campaign).
export const forCrop = (list, crop) => list.filter((x) => !x.crop || x.crop === crop);

const Ctx = createContext({ cid: "current", crop: "palm", campaign: {}, setCampaign: () => {}, setCrop: () => {} });
const KEY = "harvestCampaign";

// The campaign the planner is looking at, shared by every page and remembered in this browser.
export function CropProvider({ children }) {
  const { state } = useLive();
  const [cid, setCid] = useState(() => { try { return localStorage.getItem(KEY) || ""; } catch { return ""; } });
  const camps = useMemo(() => campaignsOf(state), [state]);
  // A campaign picked a moment ago (one just created) may not have reached the live data yet.
  const pickedAt = useRef(0);
  useEffect(() => {
    if (camps.length && !camps.some((c) => c.id === cid) && Date.now() - pickedAt.current > 5000) setCid(camps[0].id);
  }, [camps, cid]);
  const setCampaign = (id) => {
    pickedAt.current = Date.now();
    setCid(id);
    try { localStorage.setItem(KEY, id); } catch { /* storage blocked: the choice lasts this visit */ }
  };
  const campaign = camps.find((c) => c.id === cid) || camps[0] || {};
  const value = {
    cid: campaign.id || cid || "current",
    campaign,
    crop: campaign.crop || "palm",
    setCampaign,
    setCrop: (crop) => { const id = firstOfCrop(camps, crop); if (id) setCampaign(id); },
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useCrop = () => useContext(Ctx);
export const useCampaign = useCrop;
