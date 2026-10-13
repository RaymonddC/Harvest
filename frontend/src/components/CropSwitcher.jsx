import * as Menu from "@radix-ui/react-dropdown-menu";
import { campaignsOf, CROPS, cropName, multiCrop, useCrop } from "../campaigns.jsx";
import { cfg } from "../lib.js";
import { useLive } from "../live.jsx";

// The workspace card, which also picks the crop every page shows. Crops without a campaign are
// listed too, so planners see what is coming; they cannot be picked until a campaign exists.
export default function CropSwitcher() {
  const { state } = useLive();
  const { crop, setCrop } = useCrop();
  const running = new Set(campaignsOf(state).map((c) => c.crop));
  const soon = !multiCrop(state);
  return (
    <Menu.Root>
      <Menu.Trigger asChild>
        <button type="button" className="workspace-card crop-switch" aria-label={`Workspace ${cfg.millName}, crop ${cropName(crop)}. Change crop`}>
          <span>Workspace</span>
          <b>{cfg.millName}</b>
          <span className="crop-now"><i className="crop-dot" />{cropName(crop)}<span className="crop-chev" aria-hidden="true">▾</span></span>
        </button>
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content className="hc-menu crop-menu" align="start" sideOffset={6} collisionPadding={12}>
          <div className="crop-menu-head">Crop</div>
          <Menu.RadioGroup value={crop} onValueChange={setCrop}>
            {CROPS.map((c) => {
              const has = running.has(c.id);
              return (
                <Menu.RadioItem key={c.id} value={c.id} disabled={!has} className="hc-menu-item crop-item">
                  <i className={`crop-dot ${has ? "" : "off"}`} />
                  <span>{c.label}</span>
                  {!has && <span className="crop-tag">{soon ? "Coming soon" : "No campaign"}</span>}
                  <Menu.ItemIndicator className="crop-check">✓</Menu.ItemIndicator>
                </Menu.RadioItem>
              );
            })}
          </Menu.RadioGroup>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}
