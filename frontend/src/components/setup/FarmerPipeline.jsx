import { useState } from "react";
import { crmOf, REASONS, STAGES } from "../../crm.js";
import { fmtT } from "../../lib.js";
import { Avatar } from "../../ui.jsx";
import FarmerList from "./FarmerList.jsx";

const PER_COLUMN = 6;

// The campaign's farmers as a CRM pipeline: one column per stage (To call, Calling, No answer, Answered, Offer, Deal,
// Delivered), each card with the farmer's next harvest or why they need a call. "List" shows the same farmers as a
// table with their stage and reason. A filter from the chart above (farmers behind a week) narrows both.
export default function FarmerPipeline({ state, cid, title, filter, onClearFilter, onEdit, onOpen, empty }) {
  const [view, setView] = useState("board");
  const [stage, setStage] = useState(null); // list view narrowed to one stage
  const crm = crmOf(state, cid);
  let rows = crm.farmers;
  if (filter) rows = rows.filter((x) => filter.ids.has(x.farmer.id));
  if (view === "list" && stage) rows = rows.filter((x) => x.stage === stage);
  const toCall = crm.farmers.filter((x) => x.reason).length;
  const reasonText = Object.entries(crm.reasons).filter(([, n]) => n).map(([k, n]) => `${n} ${REASONS[k].toLowerCase()}`).join(", ");
  const openList = (s) => { setStage(s); setView("list"); };
  const sub = (x) => (x.stage === "offer" && x.pending ? `Offer ${fmtT(x.pending.kg)} t at ${x.pending.price_per_kg}/kg`
    : (x.stage === "deal" || x.stage === "delivered") && x.deal ? `Deal ${fmtT(x.deal.kg)} t${x.deal.delivered_kg ? `, ${fmtT(x.deal.delivered_kg)} t in` : ""}`
    : x.stage === "calling" ? "Call waiting or on now"
    : x.reason ? REASONS[x.reason]
    : x.harvest ? `${fmtT(x.harvest.kg)} t on ${new Date(`${x.harvest.ready_date}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}` : "");
  return (
    <section className="card pipeline" id="farmer-list" aria-labelledby="pipe-title">
      <div className="card-head">
        <div>
          <h2 id="pipe-title">{title}</h2>
          <span className="sub">{crm.farmers.length} farmers · <b>{toCall} need a harvest call</b>{reasonText ? ` (${reasonText})` : ""}</span>
        </div>
        <div className="seg-toggle" role="group" aria-label="View">
          <button type="button" className={view === "board" ? "on" : ""} aria-pressed={view === "board"} onClick={() => { setView("board"); setStage(null); }}>Board</button>
          <button type="button" className={view === "list" ? "on" : ""} aria-pressed={view === "list"} onClick={() => setView("list")}>List</button>
        </div>
      </div>
      <details className="who-calls">
        <summary>Who gets a harvest call, and why only {toCall} of {crm.farmers.length}?</summary>
        <p>The agent calls a farmer when the forecast has nothing current from them: <b>no harvest answer yet</b>, an <b>unsure answer</b> (it only counts for half), or a <b>harvest date that has passed</b> (the old answer is used up). You can also mark a farmer to always call. Farmers with a firm, current answer are already counted in the forecast, so they are not called again until their harvest date passes. Gap-fill calls are separate: they go to the farmers who can bring harvest forward into a short week.</p>
      </details>
      {filter && (
        <div className="pipe-filter" role="status">
          <span>Showing <b>{rows.length}</b> {filter.label}</span>
          <button type="button" className="btn sm ghost" onClick={onClearFilter}>Show all farmers</button>
        </div>
      )}
      {view === "board" ? (
        <div className="board" role="list">
          {STAGES.map((s) => {
            const items = rows.filter((x) => x.stage === s.key);
            return (
              <div key={s.key} className={`col st-${s.key}`} role="listitem" aria-label={`${s.label}: ${items.length}`}>
                <div className="col-head"><b>{s.label}</b><span className="count-pill">{items.length}</span></div>
                <small className="col-hint">{s.hint}</small>
                <ul>
                  {items.slice(0, PER_COLUMN).map((x) => (
                    <li key={x.farmer.id}>
                      <button type="button" className="pcard" onClick={() => onOpen?.(x.farmer)} aria-label={`Open ${x.farmer.name}`}>
                        <Avatar name={x.farmer.name} cls="sm" />
                        <span><b>{x.farmer.name}</b><small>{sub(x)}</small></span>
                      </button>
                    </li>
                  ))}
                </ul>
                {items.length > PER_COLUMN && <button type="button" className="btn sm ghost col-more" onClick={() => openList(s.key)}>All {items.length}</button>}
              </div>
            );
          })}
        </div>
      ) : (
        <>
          {stage && (
            <div className="pipe-filter" role="status">
              <span>Stage: <b>{STAGES.find((s) => s.key === stage)?.label}</b></span>
              <button type="button" className="btn sm ghost" onClick={() => setStage(null)}>All stages</button>
            </div>
          )}
          <FarmerList farmers={rows.map((x) => x.farmer)} onEdit={onEdit} onOpen={onOpen} cid={cid} title="" empty={empty}
            extraCol={{ label: "Stage", render: (f) => {
              const x = crm.byId.get(f.id);
              return x ? <span className={`stage-chip st-${x.stage}`}>{STAGES.find((s) => s.key === x.stage)?.label}{x.reason ? <small>{REASONS[x.reason]}</small> : null}</span> : null;
            } }} />
        </>
      )}
    </section>
  );
}
