import { useEffect, useState } from "react";
import { callChip, KIND_WORD } from "../../lib.js";
import { Avatar, Dialog, DialogClose, Pill } from "../../ui.jsx";

const ENDED = ["done", "declined", "dropped"];
const newestFirst = (a, b) => (b.started_at || b.created_at || "").localeCompare(a.started_at || a.created_at || "");

function Row({ c, onShow }) {
  const chip = callChip(c);
  const label = c.kind === "collect" ? c.farmer_name : `${c.farmer_name} · ${KIND_WORD[c.kind].replace(" call", "")}`;
  const inner = <><Avatar name={c.farmer_name} cls={`sm ${c.status === "on_call" ? "" : "grey"}`} /><span className="name">{label}</span><Pill cls={chip.cls}>{chip.text}</Pill></>;
  return c.status === "on_call" ? <div className="row">{inner}</div> : <button className="row" onClick={() => onShow(c)}>{inner}</button>;
}

// Calls on now, the last few finished, and how many are queued.
export function Calls({ calls, onShow }) {
  const sorted = [...calls].sort(newestFirst);
  const onCall = sorted.filter((c) => c.status === "on_call");
  const finished = sorted.filter((c) => ENDED.includes(c.status)).slice(0, 5 - Math.min(onCall.length, 4));
  const queued = sorted.filter((c) => c.status === "queued");
  // Keep the on-call timers ticking between updates.
  const [, tick] = useState(0);
  useEffect(() => {
    if (!onCall.length) return undefined;
    const t = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(t);
  }, [onCall.length]);
  if (!onCall.length && !finished.length && !queued.length) {
    return <div className="rows" id="calls"><p className="muted">No calls yet. Start the campaign on the Setup page.</p></div>;
  }
  return (
    <div className="rows" id="calls">
      {[...onCall, ...finished].map((c) => <Row key={c.id} c={c} onShow={onShow} />)}
      {queued.length > 0 && (
        <div className="row"><span className="avatar sm grey" aria-hidden="true">{queued.length}</span>
          <span className="name">{queued.length === 1 ? queued[0].farmer_name : `${queued.length} farmers`}</span><Pill>Queued</Pill></div>
      )}
    </div>
  );
}

// One finished call: status, summary, and the transcript when the farmer consented.
export function CallDialog({ call, onClose }) {
  const chip = call ? callChip(call) : null;
  return (
    <Dialog open={!!call} onClose={onClose} title={call ? `${call.farmer_name} · ${KIND_WORD[call.kind]}` : "Call"}>
      {call && <>
        <p style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}><Pill cls={chip.cls}>{chip.text}</Pill>{call.summary || ""}</p>
        {call.consent && call.transcript && call.transcript.length ? (
          <div className="transcript">
            {call.transcript.map((l, i) => (
              <div key={i} className={`bubble ${l.who}`}><span className="who">{l.who === "agent" ? "Agent" : call.farmer_name}</span><span>{l.text}</span>{l.translation && <span className="tr">{l.translation}</span>}</div>
            ))}
          </div>
        ) : (
          <p className="muted" style={{ margin: "12px 0" }}>{call.status === "dropped" ? "The call dropped before it finished. Answers saved during the call are kept." : "No transcript: the farmer did not consent to one being kept."}</p>
        )}
      </>}
      <DialogClose />
    </Dialog>
  );
}

// Every call, newest first, with a way into the details of finished ones.
export function CallLog({ open, calls, onClose, onShow }) {
  const all = [...calls].sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
  return (
    <Dialog open={open} onClose={onClose} title="Call log" wide>
      <div className="table-wrap" style={{ maxHeight: "60vh", overflow: "auto" }}>
        {all.length ? (
          <table>
            <thead><tr>{["Farmer", "Call", "Status", "Summary", ""].map((h) => <th key={h}>{h}</th>)}</tr></thead>
            <tbody>
              {all.map((c) => {
                const chip = callChip(c);
                return (
                  <tr key={c.id}>
                    <td>{c.farmer_name}</td><td>{KIND_WORD[c.kind]}</td><td><Pill cls={chip.cls}>{chip.text}</Pill></td>
                    <td>{c.summary || <span className="muted">–</span>}</td>
                    <td>{ENDED.includes(c.status) && <button className="btn" style={{ minHeight: 36 }} onClick={() => { onClose(); onShow(c); }}>Details</button>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : <p className="muted">No calls yet.</p>}
      </div>
      <div style={{ marginTop: 12 }}><DialogClose /></div>
    </Dialog>
  );
}
