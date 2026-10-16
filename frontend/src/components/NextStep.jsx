import { Link } from "react-router-dom";
import { campaignFor, inCampaign, useCrop } from "../campaigns.jsx";
import { api, followCalls, gapFillBody, gapFillToast, startUrl } from "../lib.js";
import { useLive } from "../live.jsx";
import { useAct } from "../toast.jsx";
import { ActButton, Icon } from "../ui.jsx";

const WAITING = ["pending", "escalated"];

// The one thing to do now, in the top bar of every page, worked out from the live data:
// decide waiting offers, answer the calls that are running, fill a short week, or start calling.
// Shows nothing when there is nothing to do, or when the page itself already leads with it.
export default function NextStep({ page }) {
  const { state } = useLive();
  const { cid } = useCrop();
  const act = useAct();
  if (!state) return null;
  const campaign = campaignFor(state, cid);
  const waiting = inCampaign(state, state.offers, cid).filter((o) => WAITING.includes(o.status)).length;
  const gap = inCampaign(state, state.forecast, cid).sort((a, b) => a.week - b.week).find((r) => r.is_gap);
  const canFill = gap && ((gap.shortlist || []).length || state.farmers.some((f) => f.type === "supplier" && f.crop === campaign.crop));
  const toCall = inCampaign(state, state.farmers, cid).filter((f) => f.to_call && f.type !== "supplier").length;

  let step = null;
  if (waiting && page !== "approvals") {
    step = <Link className="btn solid" to="/approvals"><Icon name="approvals" size={16} />Review {waiting} offer{waiting > 1 ? "s" : ""}</Link>;
  } else if (campaign.status === "running" && page !== "forecast") { // the forecast banner has this button too
    const follow = followCalls(campaign);
    step = follow.external
      ? <a className="btn solid" href={follow.href} target="_blank" rel="noopener"><Icon name="phone" size={16} />{follow.label}</a>
      : <Link className="btn solid" to={follow.href}><Icon name="phone" size={16} />{follow.label}</Link>;
  } else if (canFill && page !== "forecast") { // the forecast page leads with this in its banner
    step = (
      <ActButton className="btn solid" need="campaign.run" busy="Queuing calls…"
        run={() => act(() => api(startUrl(cid), { body: gapFillBody(state) }), gapFillToast)}>
        <Icon name="phone" size={16} />Fill week {gap.week}
      </ActButton>
    );
  } else if (toCall && !state.calls.length && page !== "setup") {
    step = <Link className="btn solid" to="/setup"><Icon name="phone" size={16} />Start calling {toCall} farmers</Link>;
  }
  if (!step) return null;
  return <div className="next-step" aria-label="Next step"><span className="ns-label">Next step</span>{step}</div>;
}
