import { useState } from "react";
import { inCampaign, useCrop } from "../campaigns.jsx";
import CallRecap from "../components/forecast/CallRecap.jsx";
import { CallLog, Calls as CallRows } from "../components/forecast/Calls.jsx";
import { KIND_WORD, maskPhone } from "../lib.js";
import { useLive } from "../live.jsx";
import Shell from "../Shell.jsx";
import { Avatar, Pill } from "../ui.jsx";

// The call client inside the dashboard: the browser "phone" that answers demo calls (call.html, embedded) on
// the left, and this campaign's calls (waiting, on now, finished, with each recap) on the right.
export default function Calls() {
  const { state } = useLive();
  const { cid, campaign } = useCrop();
  const [shown, setShown] = useState(null);
  const [logOpen, setLogOpen] = useState(false);
  const calls = state ? inCampaign(state, state.calls, cid) : [];
  const waiting = calls.filter((c) => c.status === "queued").sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""));
  const phoneOn = !!state?.settings?.phone_calls;
  const farmers = new Map((state?.farmers || []).map((f) => [f.id, f]));
  const head = (
    <div className="page-head">
      <div>
        <h1>Calls{campaign.label ? ` · ${campaign.label}` : ""}</h1>
        <p>{phoneOn
          ? "Phone calls ring the farmers' own phones and show up here live. Demo calls are answered in the phone on the left."
          : "This browser stands in for the farmer's phone: answer a waiting call on the left and play the farmer, or press Play the farmer for me. Use headphones."}</p>
      </div>
      <button className="btn" type="button" onClick={() => setLogOpen(true)}>Call log</button>
    </div>
  );
  return (
    <Shell title="Calls" head={head}>
      <div className="calls-layout">
        <section className="call-frame" aria-label="Call client">
          {/* Same origin, so the call client shares the sign-in; the microphone is allowed for the frame. */}
          <iframe title="Call client" src="/call.html?embed" allow="microphone; autoplay" />
        </section>
        <div className="calls-side">
          <section className="card" aria-labelledby="waiting-title">
            <div className="card-head"><h2 id="waiting-title">Waiting to be answered</h2><Pill>{waiting.length}</Pill></div>
            {waiting.length ? (
              <ul className="rows">
                {waiting.slice(0, 8).map((c) => (
                  <li key={c.id} className="row">
                    <Avatar name={c.farmer_name} cls="sm grey" />
                    <span className="name">{c.farmer_name}<small className="muted"> · {KIND_WORD[c.kind]}{c.channel === "twilio" ? ` · phone ${maskPhone(farmers.get(c.farmer_id)?.phone || "")}` : ""}</small></span>
                    {c.attempt > 1 && <Pill cls="amber">Retry</Pill>}
                  </li>
                ))}
                {waiting.length > 8 && <li className="row muted small">and {waiting.length - 8} more</li>}
              </ul>
            ) : <p className="muted small">No call is waiting. Start calling on the Campaign page, or press Call now on a farmer.</p>}
          </section>
          <section className="card" aria-labelledby="recent-title">
            <div className="card-head"><h2 id="recent-title">On now and recent</h2></div>
            {state ? <CallRows calls={calls.filter((c) => c.status !== "queued")} onShow={setShown} /> : <div className="rows" />}
          </section>
        </div>
      </div>
      <CallRecap call={shown} onClose={() => setShown(null)} />
      <CallLog open={logOpen} calls={calls} onClose={() => setLogOpen(false)} onShow={setShown} />
    </Shell>
  );
}
