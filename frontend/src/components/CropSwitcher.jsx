import * as Menu from "@radix-ui/react-dropdown-menu";
import { Link } from "react-router-dom";
import { campaignsOf, cropName, useCrop } from "../campaigns.jsx";
import { cfg } from "../lib.js";
import { useLive } from "../live.jsx";

// The workspace card, which also picks the campaign every page shows (grouped by crop; a crop can have several).
export default function CropSwitcher() {
  const { state } = useLive();
  const { cid, campaign, setCampaign } = useCrop();
  const camps = campaignsOf(state);
  const crops = [...new Set(camps.map((c) => c.crop))];
  return (
    <Menu.Root>
      <Menu.Trigger asChild>
        <button type="button" className="workspace-card crop-switch" aria-label={`Workspace ${cfg.millName}, campaign ${campaign.label || ""}. Change campaign`}>
          <span>Workspace</span>
          <b>{cfg.millName}</b>
          <span className="crop-now"><i className={`crop-dot ${campaign.status === "running" ? "" : "idle"}`} />{campaign.label || "No campaign"}<span className="crop-chev" aria-hidden="true">▾</span></span>
        </button>
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content className="hc-menu crop-menu" align="start" sideOffset={6} collisionPadding={12}>
          <Menu.RadioGroup value={cid} onValueChange={setCampaign}>
            {crops.map((crop) => (
              <Menu.Group key={crop}>
                <div className="crop-menu-head">{cropName(crop)}</div>
                {camps.filter((c) => c.crop === crop).map((c) => (
                  <Menu.RadioItem key={c.id} value={c.id} className="hc-menu-item crop-item">
                    <i className={`crop-dot ${c.status === "running" ? "" : "off"}`} />
                    <span>{c.label}</span>
                    {c.status === "running" && <span className="crop-tag">Calling</span>}
                    <Menu.ItemIndicator className="crop-check">✓</Menu.ItemIndicator>
                  </Menu.RadioItem>
                ))}
              </Menu.Group>
            ))}
          </Menu.RadioGroup>
          <Menu.Separator className="hc-menu-sep" />
          <Menu.Item asChild className="hc-menu-item"><Link to="/setup">Manage campaigns…</Link></Menu.Item>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}
