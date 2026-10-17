import * as RDialog from "@radix-ui/react-dialog";
import { useEffect, useState } from "react";
import { api, apiUrl, callChip, can, cropLabel, fmtKg, KIND_WORD, maskPhone, offerPoUrl, plainPrice } from "../../lib.js";
import { AgentToggle, Notes, Standing, useCrmOf } from "./Relationship.jsx";
import { useConfirm } from "../../dialogs.jsx";
import { useAct } from "../../toast.jsx";
import { ActButton, Avatar, needs, Pill } from "../../ui.jsx";
import CallRecap from "../forecast/CallRecap.jsx";
import { campaignsOf, farmerCampaign } from "../../campaigns.jsx";
import { crmOf, REASONS, STAGES } from "../../crm.js";

const day = (iso, opts = { day: "numeric", month: "short" }) => (iso ? new Date(iso.length === 10 ? iso + "T00:00:00" : iso).toLocaleDateString("en-GB", opts) : "");
const when = (iso) => (iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");

// The farmer's next harvest: shown, corrected or added by hand. A hand-made value is marked as edited and the
// farmer's own answer from the call stays visible next to it.
function HarvestBox({ farmer, harvest }) {
  const act = useAct();
  const confirm = useConfirm();
  const [form, setForm] = useState(null); // null: viewing
  const start = () => setForm({ kg: harvest ? String(harvest.kg) : "", ready_date: harvest?.ready_date || "", confidence: harvest?.confidence || "firm",
    every_days: harvest?.every_days ? String(harvest.every_days) : "" });
  const every = Number(form?.every_days);
  const valid = form && Number(form.kg) > 0 && /^\d{4}-\d{2}-\d{2}$/.test(form.ready_date) && (!form.every_days || (every >= 5 && every <= 45));
  const save = async () => {
    const r = await act(() => api(`/api/farmers/${farmer.id}/harvest`, { method: "PUT", body: { kg: Number(form.kg), ready_date: form.ready_date, confidence: form.confidence, every_days: form.every_days ? every : null } }),
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
        <label className="field">Harvests every … days <span className="sub">(optional, 5 to 45; later rounds are added to the forecast)</span>
          <input type="text" inputMode="numeric" className="num-input" style={{ maxWidth: 160 }} placeholder="e.g. 14" value={form.every_days}
            onChange={(e) => setForm({ ...form, every_days: e.target.value.replace(/[^0-9]/g, "") })} />
        </label>
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
          {", "}{harvest.confidence === "unsure" ? "unsure (counts for half)" : "firm"}
          {harvest.every_days ? `, harvests every ${harvest.every_days} days, so later rounds are in the forecast too` : ""}
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
          {a.edited_by && <span className="small muted">, edited by {a.edited_by} (agent heard “{a.original}”)</span>}
          <button type="button" className="btn sm ghost" {...needs("farmers.manage")} onClick={() => setValue(a.answer === "skipped" ? "" : a.answer)}>Edit</button>
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

// What the farmer promised against what they delivered, and adding or removing a delivery.
export function DeliveryBox({ farmer, stateKey }) {
  const act = useAct();
  const confirm = useConfirm();
  const [rec, setRec] = useState(null);
  const [tick, setTick] = useState(0);
  const [form, setForm] = useState({ date: new Date().toISOString().slice(0, 10), kg: "", unripe: "", dirt: "" });
  const pctIn = (k) => (e) => setForm({ ...form, [k]: e.target.value.replace(/[^0-9.]/g, "") });
  const net = Number(form.kg) * (1 - (Number(form.unripe || 0) + Number(form.dirt || 0)) / 100);
  useEffect(() => {
    let live = true;
    api(`/api/farmers/${farmer.id}/track-record`, { method: "GET" }).then((r) => { if (live) setRec(r); }).catch(() => {});
    return () => { live = false; };
  }, [farmer.id, stateKey, tick]);
  const add = async () => {
    const r = await act(() => api("/api/deliveries", { body: { farmer_id: farmer.id, kg: Number(form.kg), date: form.date,
      unripe_pct: form.unripe ? Number(form.unripe) : null, dirt_pct: form.dirt ? Number(form.dirt) : null } }),
      (d) => `Delivery recorded: ${fmtKg(d.net_kg)} kg net${d.po_number ? `, paid at ${d.po_number}` : ""}.`);
    if (r) { setForm({ ...form, kg: "", unripe: "", dirt: "" }); setTick((n) => n + 1); }
  };
  const remove = async (d) => {
    if (await confirm({ title: "Remove this delivery?", body: `${fmtKg(d.kg)} kg on ${day(d.date)}.`, confirm: "Remove", danger: true })) {
      await act(() => api(`/api/deliveries/${d.id}`, { method: "DELETE" }), "Delivery removed.");
      setTick((n) => n + 1);
    }
  };
  const markPaid = async (d) => {
    const ref = window.prompt(`Mark ${fmtKg(d.net_kg ?? d.kg)} kg (${d.amount != null ? plainPrice(d.amount, d.currency || "IDR") : "no amount"}) as paid. Transfer reference (optional):`, "");
    if (ref === null) return;
    await act(() => api(`/api/deliveries/${d.id}/payment`, { method: "PUT", body: { paid: true, ref } }), "Marked as paid.");
    setTick((n) => n + 1);
  };
  if (!rec) return null;
  const unpaid = rec.deliveries.filter((d) => !d.paid);
  return (
    <div className="delivery-box">
      {unpaid.length > 0 && <p className="unpaid-line"><b>{unpaid.length} {unpaid.length === 1 ? "delivery" : "deliveries"} not paid yet</b>{unpaid.some((d) => d.amount != null) ? `: ${plainPrice(unpaid.reduce((n, d) => n + (d.amount || 0), 0), unpaid[0].currency || "IDR")}` : ""}</p>}
      <p>{rec.reliability != null
        ? <><b>{Math.round(rec.reliability * 100)}%</b> of promised kg delivered, over {rec.weeks.length} recorded weeks.</>
        : rec.weeks.length ? `${rec.weeks.length} recorded week so far; a reliability score needs 2.` : "No deliveries recorded against a promise yet."}</p>
      {rec.weeks.length > 0 && (
        <ul className="fs-list">
          {rec.weeks.slice(-6).reverse().map((w) => (
            <li key={w.week_start} className="row"><span className="name">Week of {day(w.week_start)}</span>
              <span className="num">{fmtKg(w.delivered)} of {fmtKg(w.promised)} kg</span></li>
          ))}
        </ul>
      )}
      {can("farmers.manage") && (
        <div className="delivery-form">
          <label className="field">Delivered on<input type="date" value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} /></label>
          <label className="field">Gross kg<input type="text" inputMode="numeric" className="num-input" value={form.kg} onChange={(e) => setForm({ ...form, kg: e.target.value.replace(/[^0-9]/g, "") })} /></label>
          <label className="field">Unripe %<input type="text" inputMode="decimal" className="num-input" placeholder="0" value={form.unripe} onChange={pctIn("unripe")} /></label>
          <label className="field">Dirt %<input type="text" inputMode="decimal" className="num-input" placeholder="0" value={form.dirt} onChange={pctIn("dirt")} /></label>
          <ActButton className="btn sm leaf" busy="Saving…" disabled={!(Number(form.kg) > 0)} run={add}>Add delivery</ActButton>
          {Number(form.kg) > 0 && <span className="small muted">{fmtKg(Math.round(net))} kg net after grading</span>}
        </div>
      )}
      {rec.deliveries.length > 0 && (
        <details style={{ marginTop: 8 }} open={unpaid.length > 0}>
          <summary>All deliveries ({rec.deliveries.length})</summary>
          <ul className="fs-list">
            {rec.deliveries.map((d) => (
              <li key={d.id} className="row"><span className="name">{day(d.date)}, {fmtKg(d.kg)} kg{d.deduction_pct ? ` − ${d.deduction_pct}% = ${fmtKg(d.net_kg)} kg net` : ""}
                {d.amount != null && <small className="muted">, {plainPrice(d.amount, d.currency || "IDR")}{d.po_number ? ` (${d.po_number})` : " (reference price)"}</small>}</span>
                {d.paid
                  ? <span className="paid-tag" title={d.payment_ref ? `Ref. ${d.payment_ref}` : undefined}>Paid {day(d.paid_at)}</span>
                  : can("offers.decide") ? <ActButton className="btn sm" busy="Saving…" run={() => markPaid(d)}>Mark paid</ActButton>
                  : <span className="unpaid-tag">Not paid yet</span>}
                <a className="btn sm ghost" href={apiUrl(`/api/deliveries/${d.id}/receipt.pdf`)} download>Receipt</a>
                {can("farmers.manage") && <button type="button" className="btn sm ghost" onClick={() => remove(d)}>Remove</button>}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}


// The farmer's history as one timeline, newest first (a CRM contact's activity): calls, harvest answers and edits,
// offers and decisions, and deliveries.
function activityOf(state, f) {
  const out = [];
  const when = (iso) => (iso ? new Date(iso) : null);
  for (const c of state.calls.filter((x) => x.farmer_id === f.id)) {
    const t = c.ended_at || c.started_at || c.created_at;
    const what = c.status === "queued" ? "Call waiting" : c.status === "on_call" ? "On a call now"
      : `${({ collect: "Harvest call", gap_fill: "Gap-fill call", confirm: "Confirmation call" })[c.kind] || "Call"}: ${(c.outcome || c.status || "").replace(/_/g, " ")}`;
    out.push({ t, kind: "call", what, detail: c.summary || "", call: c });
  }
  const h = state.harvests.find((x) => x.farmer_id === f.id);
  if (h) {
    out.push({ t: h.updated_at || null, kind: "harvest", what: `${h.source === "call" ? "Harvest given on a call" : h.edited_by ? `Harvest edited by ${h.edited_by}` : "Harvest on record"}: ${fmtKg(h.kg)} kg ready ${h.ready_date}`,
      detail: [h.confidence === "unsure" ? "unsure" : "firm", h.every_days ? `every ${h.every_days} days` : "", h.rescheduled_from ? `moved from ${h.rescheduled_from}` : ""].filter(Boolean).join(", ") });
  }
  for (const o of state.offers.filter((x) => x.farmer_id === f.id)) {
    out.push({ t: o.created_at, kind: "offer", what: `Offer: ${fmtKg(o.kg)} kg at ${plainPrice(o.price_per_kg, o.currency || "IDR")}/kg`, detail: o.deliver_week_start ? `for the week of ${o.deliver_week_start}` : "" });
    if (o.decided_at) out.push({ t: o.decided_at, kind: o.status === "approved" ? "deal" : "offer", what: `Offer ${o.status} by ${o.decided_by || "Planner"}`, detail: o.delivered_kg ? `${fmtKg(o.delivered_kg)} kg delivered so far` : "" });
  }
  return out.filter((x) => x.t).sort((a, b) => when(b.t) - when(a.t));
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
  const cid = f && state ? farmerCampaign(f, campaignsOf(state)) : null;
  const crm = f && state && cid ? crmOf(state, cid).byId.get(f.id) : null;
  const activity = f && state ? activityOf(state, f) : [];
  const rel = useCrmOf(f?.id, JSON.stringify([state?.notes?.length, state?.calls?.length, state?.offers?.length, f?.usual_kg_week, f?.certification]));

  return (
    <RDialog.Root open={!!farmer} onOpenChange={(o) => { if (!o) onClose(); }}>
      <RDialog.Portal>
        <RDialog.Overlay className="hc-overlay" />
        <RDialog.Content className="hc-sheet" aria-describedby={undefined}>
          {f && <>
            <header className="sheet-head">
              <Avatar name={f.name} id={f.id} person />
              <div>
                <RDialog.Title className="sheet-title">{f.name}</RDialog.Title>
                <span className="sub">{[f.village, cropLabel(f.crop), f.language, maskPhone(f.phone)].filter(Boolean).join(", ")}</span>
                {f.do_not_call && <Pill cls="">Asked not to be called</Pill>}
                <AgentToggle f={f} />
                <span className="plot-line small">
                  {f.plot_lat != null && f.plot_lng != null
                    ? <>Plot <a href={`https://www.google.com/maps?q=${f.plot_lat},${f.plot_lng}`} target="_blank" rel="noopener">{f.plot_lat}, {f.plot_lng}</a>{f.plot_ha ? `, ${f.plot_ha} ha` : ""}</>
                    : <span className="muted">Plot not mapped (needed for traceability)</span>}
                  {f.certification && <>, <b>{f.certification}</b></>}
                </span>
              </div>
              <RDialog.Close className="sheet-x" aria-label="Close"><span aria-hidden="true">×</span></RDialog.Close>
            </header>
            <div className="sheet-body">
              {crm && (
                <div className={`next-action st-${crm.stage}`}>
                  <span className={`stage-chip st-${crm.stage}`}>{STAGES.find((s) => s.key === crm.stage)?.label}</span>
                  <span>{crm.reason ? <><b>Next:</b> harvest call. {REASONS[crm.reason]}.</>
                    : crm.stage === "offer" ? <><b>Next:</b> approve or reject the offer on Approvals.</>
                    : crm.stage === "deal" ? <><b>Next:</b> the delivery at the weighbridge (purchase order sent).</>
                    : crm.stage === "calling" ? <><b>Now:</b> the agent is calling.</>
                    : <><b>Nothing to do:</b> a firm, current harvest is on record.</>}</span>
                </div>
              )}
              <Standing crm={rel} />
              <section aria-labelledby="fs-harvest">
                <h3 id="fs-harvest">Next harvest</h3>
                <HarvestBox farmer={f} harvest={harvest} />
              </section>
              <section aria-labelledby="fs-track">
                <h3 id="fs-track">Track record</h3>
                <DeliveryBox farmer={f} stateKey={JSON.stringify(state?.forecast?.map((r) => r.expected_kg))} />
              </section>

              <section aria-labelledby="fs-notes">
                <h3 id="fs-notes">Notes and follow-ups</h3>
                <Notes f={f} notes={(state?.notes || []).filter((n) => n.farmer_id === f.id)} />
              </section>

              <section aria-labelledby="fs-activity">
                <h3 id="fs-activity">Activity <span className="sub">({activity.length})</span></h3>
                {activity.length ? (
                  <ol className="timeline">
                    {activity.slice(0, 12).map((a, i) => (
                      <li key={i} className={`tl-${a.kind}`}>
                        <i aria-hidden="true" />
                        <div>
                          {a.call ? <button type="button" className="linkish" onClick={() => setShownCall(a.call)}><b>{a.what}</b></button> : <b>{a.what}</b>}
                          {a.detail && <small>{a.detail}</small>}
                          <time dateTime={a.t}>{new Date(a.t).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</time>
                        </div>
                      </li>
                    ))}
                  </ol>
                ) : <p className="muted">Nothing yet. The first harvest call starts the history.</p>}
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
                            <span className="name">{KIND_WORD[c.kind]}, {when(c.started_at || c.created_at)}{c.summary ? `, ${c.summary}` : ""}</span>
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
                        <Pill cls={o.status === "approved" ? "mint" : o.status === "pending" ? "amber" : ""}>{{ pending: "Waiting for you", escalated: "Above the ceiling", approved: o.confirmed_by_voice ? "Approved, confirmed" : "Approved", rejected: "Rejected" }[o.status] || o.status}</Pill>
                        {o.status === "approved" && <a className="btn sm ghost" href={apiUrl(offerPoUrl(o.id))} download>Purchase order</a>}
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
