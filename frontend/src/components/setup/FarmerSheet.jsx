import * as RDialog from "@radix-ui/react-dialog";
import { useState } from "react";
import { api, callChip, can, cropLabel, fmtKg, KIND_WORD, maskPhone, plainPrice } from "../../lib.js";
import { useConfirm } from "../../dialogs.jsx";
import { useAct } from "../../toast.jsx";
import { ActButton, Avatar, Pill } from "../../ui.jsx";
import CallRecap from "../forecast/CallRecap.jsx";

const day = (iso, opts = { day: "numeric", month: "short" }) => (iso ? new Date(iso.length === 10 ? iso + "T00:00:00" : iso).toLocaleDateString("en-GB", opts) : "");
const when = (iso) => (iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");

// The farmer's next harvest: shown, corrected or added by hand. A hand-made value is marked as edited and the
// farmer's own answer from the call stays visible next to it.
function HarvestBox({ farmer, harvest }) {
  const act = useAct();
  const confirm = useConfirm();
  const [form, setForm] = useState(null); // null: viewing
  const start = () => setForm({ kg: harvest ? String(harvest.kg) : "", ready_date: harvest?.ready_date || "", confidence: harvest?.confidence || "firm" });
  const valid = form && Number(form.kg) > 0 && /^\d{4}-\d{2}-\d{2}$/.test(form.ready_date);
  const save = async () => {
    const r = await act(() => api(`/api/farmers/${farmer.id}/harvest`, { method: "PUT", body: { kg: Number(form.kg), ready_date: form.ready_date, confidence: form.confidence } }),
      "Harvest saved. The forecast is updated.");
    if (r) setForm(null);
  };
  const remove = async () => {
    if (await confirm({ title: "Remove this harvest?", body: "It leaves the forecast. The calls and their transcripts stay.", confirm: "Remove harvest", danger: true })) {
      act(() => api(`/api/farmers/${farmer.id}/harvest`, { method: "DELETE" }), "Harvest removed.");
    }
  };
  const allowed = can("farmers.manage");

  if (form) {
    return (
      <div className="harvest-edit">
        <div className="grid3">
          <label className="field">Volume (kg)
            <input type="text" inputMode="numeric" className="num-input" value={form.kg} onChange={(e) => setForm({ ...form, kg: e.target.value.replace(/[^0-9]/g, "") })} />
          </label>
          <label className="field">Ready on
            <input type="date" value={form.ready_date} onChange={(e) => setForm({ ...form, ready_date: e.target.value })} />
          </label>
          <label className="field">How sure
            <select value={form.confidence} onChange={(e) => setForm({ ...form, confidence: e.target.value })}>
              <option value="firm">Firm</option><option value="unsure">Unsure (counts for half)</option>
            </select>
          </label>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <ActButton className="btn sm leaf" busy="Saving…" disabled={!valid} run={save}>Save harvest</ActButton>
          <button type="button" className="btn sm ghost" onClick={() => setForm(null)}>Cancel</button>
        </div>
      </div>
    );
  }
  return (
    <div className="harvest-view">
      {harvest ? (
        <>
          <b className="num">{fmtKg(harvest.kg)} kg</b> ready {day(harvest.ready_date, { weekday: "short", day: "numeric", month: "short" })}
          {" · "}{harvest.confidence === "unsure" ? "unsure (counts for half)" : "firm"}
          {harvest.edited_by && (
            <p className="small muted" style={{ margin: "4px 0 0" }}>
              Edited by {harvest.edited_by}{harvest.edited_at ? `, ${when(harvest.edited_at)}` : ""}.
              {harvest.original ? ` The farmer said ${fmtKg(harvest.original.kg)} kg, ready ${day(harvest.original.ready_date)}${harvest.original.confidence === "unsure" ? " (unsure)" : ""}.` : " Added by hand, not from a call."}
            </p>
          )}
        </>
      ) : <span className="muted">No harvest on record yet.</span>}
      <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
        <button type="button" className="btn sm" disabled={!allowed} onClick={start}>{harvest ? "Edit harvest" : "Add harvest"}</button>
        {harvest && <button type="button" className="btn sm ghost" disabled={!allowed} onClick={remove}>Remove</button>}
      </div>
    </div>
  );
}

// One answer to the planner's questions, corrected in place. The agent's version stays visible once edited.
function AnswerRow({ call, qid, a }) {
  const act = useAct();
  const [value, setValue] = useState(null);
  const save = async () => {
    const r = await act(() => api(`/api/calls/${call.id}/answers/${qid}`, { method: "PUT", body: { answer: value } }), "Answer saved.");
    if (r) setValue(null);
  };
  return (
    <li className="answer-row">
      <div className="q"><span className="label">{a.question}</span><span className="sub">{day(call.started_at || call.created_at)}</span></div>
      {value === null ? (
        <div className="a">
          <b>{a.answer === "skipped" ? "Did not answer" : a.answer}</b>
          {a.edited_by && <span className="small muted"> · edited by {a.edited_by} (agent heard “{a.original}”)</span>}
          <button type="button" className="btn sm ghost" disabled={!can("farmers.manage")} onClick={() => setValue(a.answer === "skipped" ? "" : a.answer)}>Edit</button>
        </div>
      ) : (
        <div className="a">
          <input type="text" aria-label={`Answer to ${a.question}`} value={value} onChange={(e) => setValue(e.target.value)}
            placeholder={a.type === "yes_no" ? "yes or no" : a.type === "number" ? "a number" : "the answer"} />
          <ActButton className="btn sm leaf" busy="Saving…" disabled={!value.trim()} run={save}>Save</ActButton>
          <button type="button" className="btn sm ghost" onClick={() => setValue(null)}>Cancel</button>
        </div>
      )}
    </li>
  );
}

// Everything about one farmer in one place: profile, next harvest (editable), every call (opens the recap),
// offers and answers to the planner's questions (editable).
export default function FarmerSheet({ farmer, state, onClose }) {
  const [shownCall, setShownCall] = useState(null);
  const f = farmer && state ? state.farmers.find((x) => x.id === farmer.id) || farmer : farmer;
  const harvest = f && state ? state.harvests.find((h) => h.farmer_id === f.id) : null;
  const calls = f && state ? state.calls.filter((c) => c.farmer_id === f.id)
    .sort((a, b) => (b.started_at || b.created_at || "").localeCompare(a.started_at || a.created_at || "")) : [];
  const offers = f && state ? state.offers.filter((o) => o.farmer_id === f.id)
    .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || "")) : [];
  const answers = calls.flatMap((c) => Object.entries(c.answers || {}).map(([qid, a]) => ({ call: c, qid, a })));

  return (
    <RDialog.Root open={!!farmer} onOpenChange={(o) => { if (!o) onClose(); }}>
      <RDialog.Portal>
        <RDialog.Overlay className="hc-overlay" />
        <RDialog.Content className="hc-sheet" aria-describedby={undefined}>
          {f && <>
            <header className="sheet-head">
              <Avatar name={f.name} person />
              <div>
                <RDialog.Title className="sheet-title">{f.name}</RDialog.Title>
                <span className="sub">{[f.village, cropLabel(f.crop), f.language, maskPhone(f.phone)].filter(Boolean).join(" · ")}</span>
                {f.do_not_call && <Pill cls="">Asked not to be called</Pill>}
              </div>
              <RDialog.Close className="sheet-x" aria-label="Close"><span aria-hidden="true">×</span></RDialog.Close>
            </header>
            <div className="sheet-body">
              <section aria-labelledby="fs-harvest">
                <h3 id="fs-harvest">Next harvest</h3>
                <HarvestBox farmer={f} harvest={harvest} />
              </section>

              <section aria-labelledby="fs-calls">
                <h3 id="fs-calls">Calls <span className="sub">({calls.length})</span></h3>
                {calls.length ? (
                  <ul className="fs-list">
                    {calls.map((c) => {
                      const chip = callChip(c);
                      return (
                        <li key={c.id}>
                          <button type="button" className="row" onClick={() => setShownCall(c)}>
                            <span className="name">{KIND_WORD[c.kind]} · {when(c.started_at || c.created_at)}{c.summary ? ` · ${c.summary}` : ""}</span>
                            <Pill cls={chip.cls}>{chip.text}</Pill>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                ) : <p className="muted">No calls yet.</p>}
              </section>

              <section aria-labelledby="fs-offers">
                <h3 id="fs-offers">Offers <span className="sub">({offers.length})</span></h3>
                {offers.length ? (
                  <ul className="fs-list">
                    {offers.map((o) => (
                      <li key={o.id} className="row">
                        <span className="name">{fmtKg(o.kg)} kg to week {o.deliver_week} at {plainPrice(o.price_per_kg, o.currency || "IDR")}/kg</span>
                        <Pill cls={o.status === "approved" ? "mint" : o.status === "pending" ? "amber" : ""}>{{ pending: "Waiting for you", escalated: "Above the ceiling", approved: o.confirmed_by_voice ? "Approved · confirmed" : "Approved", rejected: "Rejected" }[o.status] || o.status}</Pill>
                      </li>
                    ))}
                  </ul>
                ) : <p className="muted">No offers.</p>}
              </section>

              <section aria-labelledby="fs-answers">
                <h3 id="fs-answers">Answers to your questions <span className="sub">({answers.length})</span></h3>
                {answers.length ? <ul className="fs-list answers">{answers.map((x) => <AnswerRow key={x.call.id + x.qid} {...x} />)}</ul>
                  : <p className="muted">No answers yet. Questions are set on the agent card and asked on harvest calls.</p>}
              </section>
            </div>
            <CallRecap call={shownCall} onClose={() => setShownCall(null)} />
          </>}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}
