import { useRef, useState } from "react";
import { toast } from "sonner";
import { crmOf, REASONS, STAGES } from "../../crm.js";
import { api, can, fmtT, numberAllowed } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import FarmerFace from "../FarmerFace.jsx";
import FarmerList from "./FarmerList.jsx";

const PER_COLUMN = 6;
const EMPTY = {
  to_call: "Everyone has a current answer.",
  calling: "No call is waiting.",
  no_reply: "Every call got through.",
  answered: "No firm answers yet.",
  offer: "Nothing waiting for you.",
  deal: "No deals yet.",
  delivered: "Nothing weighed yet.",
};

// Drag and drop: a stage comes from what happened (calls, answers, offers), so only moves that are a real action are
// allowed; any other drop says why.
const WHY_NOT = {
  no_reply: "No answer is set when a call does not reach the farmer.",
  answered: "Answered is set by the farmer's answer on a call. Drag them to Calling to call them.",
  offer: "An offer comes from a gap-fill call, made by the agent inside your price range.",
  delivered: "Delivered is set when the weighbridge records the delivery (the farmer's page or the CSV upload).",
  deal: "Only an offer that is waiting can be approved into a deal.",
};

// The campaign's farmers as a CRM pipeline: one column per stage (To call, Calling, No answer, Answered, Offer, Deal,
// Delivered), each card with the farmer's next harvest or why they need a call. "List" shows the same farmers as a
// table with their stage and reason. A filter from the chart above (farmers behind a week) narrows both.
export default function FarmerPipeline({ state, cid, title, filter, onClearFilter, onEdit, onOpen, empty }) {
  const [view, setView] = useState("board");
  const [stage, setStage] = useState(null); // list view narrowed to one stage
  const [drag, setDrag] = useState(null); // the card being dragged (for its look)
  const dragged = useRef(null); // the same, at once (state lands a render later than the first dragover)
  const [over, setOver] = useState(null); // the column under it
  const act = useAct();
  const phoneCalls = !!state.settings?.phone_calls;
  const drop = async (x, to) => {
    setDrag(null); setOver(null); dragged.current = null;
    if (!x || x.stage === to) return;
    const f = x.farmer;
    if (to === "to_call") {
      if (!can("farmers.manage")) return toast.error("Your role cannot change who is called.");
      return act(() => api(`/api/farmers/${f.id}/to-call`, { method: "PUT", body: { to_call: true } }), `${f.name} will get a harvest call on the next round.`);
    }
    if (to === "calling") {
      if (!can("campaign.run")) return toast.error("Your role cannot start calls.");
      if (x.stage === "calling") return null;
      const byPhone = phoneCalls && numberAllowed(state, f.phone);
      return act(() => api(`/api/farmers/${f.id}/${byPhone ? "dial" : "call"}`, { body: {} }),
        byPhone ? `Calling ${f.name}'s phone…` : `Call to ${f.name} queued on the demo phone (Calls page).`);
    }
    if (to === "deal" && x.stage === "offer" && x.pending) {
      if (!can("offers.decide")) return toast.error("Your role cannot approve offers.");
      return act(() => api(`/api/offers/${x.pending.id}/approve`, { body: {} }), `Deal approved for ${f.name}. The agent will call to confirm it.`);
    }
    return toast(WHY_NOT[to] || "That move is not an action.", { description: `${f.name} stays in ${STAGES.find((s) => s.key === x.stage)?.label}.` });
  };
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
        <summary>Who gets a harvest call, and why only {toCall} of {crm.farmers.length}? Can I drag cards?</summary>
        <p>The agent calls a farmer when the forecast has nothing current from them: <b>no harvest answer yet</b>, an <b>unsure answer</b> (it only counts for half), or a <b>harvest date that has passed</b> (the old answer is used up). You can also mark a farmer to always call. Farmers with a firm, current answer are already counted in the forecast, so they are not called again until their harvest date passes. Gap-fill calls are separate: they go to the farmers who can bring harvest forward into a short week.</p>
        <p><b>Dragging a card:</b> to <b>To call</b> marks the farmer to be called on the next round; to <b>Calling</b> calls them now; an offer to <b>Deal</b> approves it. The other stages follow what happens on the calls and at the weighbridge, so they cannot be set by hand.</p>
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
              <div key={s.key} className={`col st-${s.key} ${over === s.key ? "drop-on" : ""}`} role="listitem" aria-label={`${s.label}: ${items.length}`}
                onDragOver={(e) => { if (dragged.current) { e.preventDefault(); setOver(s.key); } }} onDragLeave={() => setOver((o) => (o === s.key ? null : o))}
                onDrop={(e) => { e.preventDefault(); drop(dragged.current, s.key); }}>
                <div className="col-head">
                  <span className="col-n num">{items.length}</span>
                  <span className="col-name"><b>{s.label}</b><small>{s.hint}</small></span>
                </div>
                {!items.length && <p className="col-empty">{EMPTY[s.key]}</p>}
                <ul>
                  {items.slice(0, PER_COLUMN).map((x) => (
                    <li key={x.farmer.id}>
                      <button type="button" className={`pcard ${drag?.farmer.id === x.farmer.id ? "dragging" : ""}`} onClick={() => onOpen?.(x.farmer)} aria-label={`Open ${x.farmer.name}`}
                        draggable onDragStart={(e) => { dragged.current = x; setDrag(x); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", x.farmer.id); }}
                        onDragEnd={() => { dragged.current = null; setDrag(null); setOver(null); }}>
                        <FarmerFace name={x.farmer.name} id={x.farmer.id} size={34} />
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
