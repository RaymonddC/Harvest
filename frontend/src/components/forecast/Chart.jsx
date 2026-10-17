import * as Tooltip from "@radix-ui/react-tooltip";
import { useEffect, useState } from "react";
import { fmtT } from "../../lib.js";

export const shortDate = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });

// Axis ticks every 5, 10, 20, 25, 50 or 100 tonnes, whichever gives about five steps.
function ticks(maxKg) {
  const raw = maxKg / 5 / 1000;
  const step = ([5, 10, 20, 25, 50, 100, 200, 250, 500].find((n) => n >= raw) || 1000) * 1000;
  const out = [];
  for (let v = 0; v <= maxKg; v += step) out.push(v);
  return out;
}

// The bar's layers. Harvest moved out to another week by an approved deal is taken off the top,
// so the layers always add up to the expected tonnes.
function parts(r) {
  const raw = [["firm", r.firm_kg || 0], ["unsure", r.unsure_weighted_kg || 0], ["projected", r.projected_kg || 0], ["approved", r.approved_in_kg || 0]];
  let over = raw.reduce((n, [, v]) => n + v, 0) - r.expected_kg;
  for (let i = raw.length - 1; i >= 0 && over > 0; i--) {
    const cut = Math.min(raw[i][1], over);
    raw[i][1] -= cut;
    over -= cut;
  }
  return raw;
}

const Line = ({ label, kg }) => <div><span>{label}</span><b className="num">{fmtT(kg)} t</b></div>;

// One week's breakdown (Radix keeps it on screen near the edges).
function TipBody({ r, target }) {
  return (
    <>
      <strong>{r.label} · {shortDate(r.week_start)}</strong>
      <Line label="Firm answers" kg={r.firm_kg} />
      {r.unsure_weighted_kg > 0 && <Line label={r.unsure_count ? `${r.unsure_count} unsure, counted half` : "Unsure, counted half"} kg={r.unsure_weighted_kg} />}
      {r.projected_kg > 0 && <Line label="Later harvest rounds (projected)" kg={r.projected_kg} />}
      {r.approved_in_kg > 0 && <Line label="Approved deals" kg={r.approved_in_kg} />}
      {r.pending_kg > 0 && <Line label="Waiting for approval" kg={r.pending_kg} />}
      {r.capacity_kg ? <Line label={r.is_surplus ? "Over the mill's capacity" : "Mill capacity"} kg={r.is_surplus ? r.surplus_kg : r.capacity_kg} /> : null}
      <div className="sum"><span>Expected</span><b className="num">{fmtT(r.expected_kg)} of {fmtT(target)} t</b></div>
      <p className={r.is_gap ? "short" : "fine"}>
        {r.is_gap ? `${fmtT(r.gap_kg)} t short of the target` : r.gap_kg ? `${fmtT(r.gap_kg)} t under target, within the gap threshold` : "At or above the target"}
      </p>
    </>
  );
}

// A week's column opens its breakdown on hover, keyboard focus or a tap (Radix tooltips ignore
// taps on their own, so a tap toggles it here).
function Col({ r, target, children }) {
  const [open, setOpen] = useState(false);
  return (
    <Tooltip.Root open={open} onOpenChange={setOpen}>
      <Tooltip.Trigger asChild>
        <div className={`col ${r.is_gap ? "is-gap" : ""} ${r.before_start ? "before-start" : ""}`} tabIndex={0} onClick={() => setOpen((o) => !o)}>{children}</div>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className="chart-tip" side="top" sideOffset={6} collisionPadding={12}>
          <TipBody r={r} target={target} />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

// Bars grow up from the axis when the page opens; later updates slide each bar to its new
// height (the CSS transition does the motion, React only changes the height).
export default function Chart({ rows }) {
  const [grown, setGrown] = useState(false);
  const [entering, setEntering] = useState(true);
  useEffect(() => {
    let t;
    const f = requestAnimationFrame(() => requestAnimationFrame(() => { setGrown(true); t = setTimeout(() => setEntering(false), 1200); }));
    return () => { cancelAnimationFrame(f); clearTimeout(t); };
  }, []);
  const target = rows[0].target_kg;
  const cap = rows[0].capacity_kg || 0;
  // Headroom above the tallest bar for its label (and the pending part on top).
  const max = Math.max(target * 1.15, cap * 1.12, ...rows.map((r) => (r.expected_kg + r.pending_kg) * 1.15));
  const pct = (kg) => (grown ? `${(kg / max) * 100}%` : "0%");
  const at = (kg) => `${(kg / max) * 100}%`;
  return (
    <Tooltip.Provider delayDuration={120}>
      <div className={`chart has-axis ${entering ? "enter" : ""}`} role="img"
        aria-label={rows.map((r) => `${r.label} ${fmtT(r.expected_kg)} tonnes${r.is_gap ? ", gap" : ""}`).join("; ")}>
        <div className="axis" aria-hidden="true">
          {ticks(max).map((v) => <div key={v} className="tick" style={{ bottom: at(v) }}><span>{fmtT(v)}</span></div>)}
          <span className="unit">t</span>
        </div>
        <div className="target" data-label={`Target ${fmtT(target)} t`} style={{ bottom: at(target) }} />
        {cap > 0 && <div className="capacity" data-label={`Mill capacity ${fmtT(cap)} t`} style={{ bottom: at(cap) }} />}
        <div className="bars">
          {rows.map((r) => (
            <Col key={r.week} r={r} target={target}>
              <div className="val num">
                {/* On a phone the shortfall moves out of the pill (the KPI card above still shows it). */}
                <span>{fmtT(r.expected_kg)}</span>
                {r.is_gap && <span className="short">{fmtT(r.gap_kg)} t short</span>}
                {r.is_surplus && <span className="short over">{fmtT(r.surplus_kg)} t over</span>}
                {r.pending_kg > 0 && <small><span>+{fmtT(r.pending_kg)} pending</span></small>}
              </div>
              <div className="pend" hidden={!r.pending_kg} style={{ height: pct(r.pending_kg) }} title={`${fmtT(r.pending_kg)} t waiting for approval`} />
              <div className={`bar ${r.is_gap ? "gap" : ""}`} style={{ height: pct(r.expected_kg) }}>
                {/* What the week stands on, bottom up: firm answers, unsure ones (counted half), projected later rounds, approved deals. */}
                {parts(r).map(([k, v]) => v > 0 && <i key={k} className={`seg ${k}`} style={{ flexGrow: v }} />)}
              </div>
              {/* The missing tonnes, drawn from the top of the bar up to the target line. */}
              {r.is_gap && <div className="shortfall" aria-hidden="true"
                style={{ bottom: pct(r.expected_kg + r.pending_kg), height: grown ? at(Math.max(target - r.expected_kg - r.pending_kg, 0)) : "0%" }} />}
            </Col>
          ))}
        </div>
      </div>
      <div className="xlabels has-axis" aria-hidden="true">
        {rows.map((r) => <span key={r.week} className={`${r.is_gap ? "gap" : ""} ${r.before_start ? "before-start" : ""}`}>{r.label}<small>{r.before_start ? "not started" : shortDate(r.week_start)}</small></span>)}
      </div>
    </Tooltip.Provider>
  );
}
