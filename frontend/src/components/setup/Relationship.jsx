import { useEffect, useState } from "react";
import { api, can } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { ActButton } from "../../ui.jsx";

// The farmer relationship on the farmer's panel: their segment and any churn signals, the Agent calls toggle, and the
// planner's own notes (a call or visit they made, the farmer's feedback with a rating, a complaint) with follow-ups.

export const SEGMENT_WORD = {
  reliability: { reliable: "Reliable", mixed: "Mixed record", unreliable: "Unreliable", new: "New" },
  size: { small: "Small", medium: "Medium", large: "Large" },
  certified: { yes: "Certified", no: "Not certified" },
};
const KINDS = [["note", "Note"], ["call", "Call I made"], ["visit", "Visit"], ["feedback", "Feedback"], ["complaint", "Complaint"]];
const KIND_WORD = Object.fromEntries(KINDS);
const today = () => new Date().toISOString().slice(0, 10);
const day = (iso) => (iso ? new Date(`${iso.slice(0, 10)}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) : "");

// What /api/crm says about this farmer (segment, reliability, churn signals); refreshed when the data changes.
export function useCrmOf(farmerId, key) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let live = true;
    api("/api/crm", { method: "GET" }).then((r) => { if (live) setData(r); }).catch(() => {});
    return () => { live = false; };
  }, [farmerId, key]);
  return data?.farmers?.[farmerId] || null;
}

// The switch that lets the AI agent phone this farmer. Off, the planner calls them by hand; on, their number may also
// get real calls (it is the allowlist).
export function AgentToggle({ f }) {
  const act = useAct();
  const on = !!f.agent_calls;
  const flip = () => act(() => api(`/api/farmers/${f.id}/agent-calls`, { method: "PUT", body: { agent_calls: !on } }),
    on ? `${f.name} is yours to call now.` : `The agent will phone ${f.name}.`);
  return (
    <label className={`agent-toggle ${on ? "on" : ""}`}>
      <input type="checkbox" role="switch" checked={on} onChange={flip} disabled={!can("campaign.run")} />
      <span className="track" aria-hidden="true"><i /></span>
      <span>{on ? "The agent calls this farmer" : "You call this farmer"}</span>
    </label>
  );
}

export function Standing({ crm }) {
  if (!crm) return null;
  const s = crm.segment;
  return (
    <div className="standing">
      <p className="seg-line">
        {SEGMENT_WORD.reliability[s.reliability]}{crm.reliability != null ? ` (${Math.round(crm.reliability * 100)}% of promises kept)` : ""}
        {" · "}{SEGMENT_WORD.size[s.size]} grower · {SEGMENT_WORD.certified[s.certified]}
      </p>
      {crm.churn.length > 0 && (
        <div className="churn" role="note">
          <b>May be drifting away</b>
          <ul>{crm.churn.map((c) => <li key={c.key}>{c.text}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

export function Notes({ f, notes }) {
  const act = useAct();
  const [form, setForm] = useState({ kind: "call", text: "", rating: "", follow: "" });
  const rated = form.kind === "feedback" || form.kind === "complaint";
  const add = async () => {
    const r = await act(() => api(`/api/farmers/${f.id}/notes`, { body: { kind: form.kind, text: form.text,
      rating: rated && form.rating ? Number(form.rating) : null, follow_up_on: form.follow || null } }),
      form.follow ? `Saved. Follow-up on ${day(form.follow)}.` : "Saved.");
    if (r) setForm({ kind: form.kind, text: "", rating: "", follow: "" });
  };
  const list = [...notes].sort((a, b) => (b.at || "").localeCompare(a.at || ""));
  return (
    <div className="notes">
      {can("farmers.manage") && (
        <div className="note-form">
          <div className="note-row">
            <select aria-label="What kind" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              {KINDS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
            {rated && (
              <select aria-label="Rating" value={form.rating} onChange={(e) => setForm({ ...form, rating: e.target.value })}>
                <option value="">Rating</option>
                {[5, 4, 3, 2, 1].map((n) => <option key={n} value={n}>{n} of 5</option>)}
              </select>
            )}
            <label className="follow">Follow up on<input type="date" min={today()} value={form.follow} onChange={(e) => setForm({ ...form, follow: e.target.value })} /></label>
          </div>
          <textarea aria-label="What happened" rows={2} maxLength={1000} placeholder={form.kind === "complaint" ? "What the farmer is unhappy about" : "What was said or agreed"}
            value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} />
          <ActButton className="btn sm solid" busy="Saving…" disabled={!form.text.trim() && !(rated && form.rating)} run={add}>Save</ActButton>
        </div>
      )}
      {list.length ? (
        <ul className="note-list">
          {list.map((n) => (
            <li key={n.id} className={`${n.kind} ${n.done ? "done" : ""}`}>
              <div className="note-head">
                <b>{KIND_WORD[n.kind] || n.kind}{n.rating ? ` · ${n.rating} of 5` : ""}</b>
                <span className="muted">{day(n.at)} · {n.by}</span>
              </div>
              {n.text && <p>{n.text}</p>}
              {(n.follow_up_on || n.kind === "complaint") && (
                <label className="note-done">
                  <input type="checkbox" checked={!!n.done} disabled={!can("farmers.manage")}
                    onChange={() => act(() => api(`/api/notes/${n.id}/done`, { method: "PUT", body: { done: !n.done } }), n.done ? "Opened again." : "Done.")} />
                  {n.kind === "complaint" ? (n.done ? "Resolved" : "Resolve") : n.done ? `Followed up` : `Follow up on ${day(n.follow_up_on)}`}
                </label>
              )}
            </li>
          ))}
        </ul>
      ) : <p className="muted">No notes yet. Log your own calls and visits here, with a date to follow up.</p>}
    </div>
  );
}

// Follow-ups that are due today or overdue, across the farmers given (for the to-do list).
export function dueFollowUps(state, farmerIds) {
  const t = today();
  return (state?.notes || []).filter((n) => n.follow_up_on && !n.done && n.follow_up_on <= t && (!farmerIds || farmerIds.has(n.farmer_id)));
}
