import * as RDialog from "@radix-ui/react-dialog";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, callChip, fmtT, KIND_WORD, plainPrice } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { useLive } from "../../live.jsx";
import { ActButton, Avatar, Icon, Pill } from "../../ui.jsx";
import { shortDate } from "./Chart.jsx";

const length = (c) => {
  if (!c.started_at || !c.ended_at) return null;
  const s = Math.max(0, Math.round((new Date(c.ended_at) - new Date(c.started_at)) / 1000));
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
};
const clock = (iso) => (iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");

// The forecast week a date falls in, from that crop's forecast rows.
function weekOf(rows, iso) {
  if (!iso) return null;
  const d = new Date(iso + "T00:00:00");
  return rows.find((r) => { const s = new Date(r.week_start + "T00:00:00"); return d >= s && d < new Date(s.getTime() + 7 * 864e5); }) || null;
}

// One thing the agent got from the call: a tick when it has it, a dash when it does not.
const Fact = ({ ok, label, children }) => (
  <li className={ok ? "ok" : "none"}>
    <span className="mark" aria-hidden="true">{ok ? <Icon name="check" size={14} /> : "–"}</span>
    <div><span className="label">{label}</span><b>{children}</b></div>
  </li>
);

// A finished call, opened from the calls list: what the agent captured, then the conversation.
// It reads the call's harvest answer and offer from the live data, so it stays current
// while the panel is open (an offer approved meanwhile shows as approved).
export default function CallRecap({ call, onClose }) {
  const { state } = useLive();
  const act = useAct();
  const [english, setEnglish] = useState(true);
  const c = (call && state?.calls.find((x) => x.id === call.id)) || call;
  const harvest = c && state ? state.harvests.find((h) => h.call_id === c.id) : null;
  const offer = c && state ? state.offers.find((o) => o.call_id === c.id) : null;
  const crop = harvest?.crop || offer?.crop;
  const rows = state ? state.forecast.filter((r) => !crop || !r.crop || r.crop === crop) : [];
  const hw = harvest ? weekOf(rows, harvest.ready_date) : null;
  const chip = c ? callChip(c) : null;
  const lines = c?.consent && c.transcript?.length ? c.transcript : null;
  const translated = lines?.some((l) => l.translation);
  const village = c && state ? state.farmers.find((f) => f.id === c.farmer_id)?.village : "";

  return (
    <RDialog.Root open={!!call} onOpenChange={(o) => { if (!o) onClose(); }}>
      <RDialog.Portal>
        <RDialog.Overlay className="hc-overlay" />
        <RDialog.Content className="hc-sheet" aria-describedby={undefined}>
          {c && <>
            <header className="sheet-head">
              <Avatar name={c.farmer_name} person />
              <div>
                <RDialog.Title className="sheet-title">{c.farmer_name}</RDialog.Title>
                <span className="sub">{[village, KIND_WORD[c.kind], clock(c.started_at || c.created_at), length(c)].filter(Boolean).join(" · ")}</span>
              </div>
              <RDialog.Close className="sheet-x" aria-label="Close"><span aria-hidden="true">×</span></RDialog.Close>
            </header>

            <div className="sheet-body">
              <div className="recap-status"><Pill cls={chip.cls}>{chip.text}</Pill>{c.summary && <p>{c.summary}</p>}</div>

              <section aria-labelledby="captured-title">
                <h3 id="captured-title">What the agent captured</h3>
                <ul className="facts">
                  <Fact ok={!!c.consent} label="Recording">{c.consent ? "Farmer agreed to it" : "Not agreed, so no transcript is kept"}</Fact>
                  {c.kind !== "confirm" && (
                    <Fact ok={!!harvest} label="Next harvest">
                      {harvest ? <>{fmtT(harvest.kg)} t{hw ? `, ${hw.label} (from ${shortDate(hw.week_start)})` : ""}{harvest.confidence === "unsure" ? ", not sure yet" : ", firm"}</> : "Not given on this call"}
                    </Fact>
                  )}
                  {(c.kind === "gap_fill" || offer) && (
                    <Fact ok={!!offer} label="Deal">
                      {offer ? <>{fmtT(offer.kg)} t to week {offer.deliver_week} at {plainPrice(offer.price_per_kg, offer.currency || "IDR")}/kg
                        <span className={`deal-state ${offer.status}`}>{{ pending: "waiting for you", escalated: "above the ceiling", approved: "approved", rejected: "rejected" }[offer.status] || offer.status}</span></> : "No deal agreed"}
                    </Fact>
                  )}
                  {!harvest && c.harvest_read_back && (
                    <li className="none">
                      <span className="mark" aria-hidden="true">!</span>
                      <div><span className="label">Read back, not confirmed</span>
                        <b>{c.harvest_read_back.kg.toLocaleString("en-US")} kg, ready {new Date(c.harvest_read_back.ready_date + "T00:00:00").toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}</b>
                        <span className="sub" style={{ display: "block" }}>The agent read this back but the call ended before it was saved. Check the conversation below, then save it.</span>
                        <ActButton need="farmers.manage" className="btn sm leaf" busy="Saving…" style={{ marginTop: 6 }}
                          run={() => act(() => api(`/api/calls/${c.id}/confirm-harvest`, { body: {} }), "Harvest saved. The forecast is updated.")}>Save this harvest</ActButton>
                      </div>
                    </li>
                  )}
                  {Object.values(c.answers || {}).map((a) => (
                    <Fact key={a.question} ok={a.answer !== "skipped"} label={a.question}>{a.answer === "skipped" ? "Farmer did not answer" : a.answer}{a.edited_by ? ` (edited by ${a.edited_by})` : ""}</Fact>
                  ))}
                  {c.kind === "confirm" && <Fact ok={c.status === "done"} label="Confirmation">{c.status === "done" ? "Farmer heard the approved deal" : "Not confirmed yet"}</Fact>}
                </ul>
                {offer && ["pending", "escalated"].includes(offer.status) && (
                  <Link className="btn solid" to="/approvals" onClick={onClose}><Icon name="approvals" size={16} />Review this offer</Link>
                )}
              </section>

              <section aria-labelledby="talk-title">
                <div className="talk-head">
                  <h3 id="talk-title">Conversation</h3>
                  {translated && (
                    <label className="switch"><input type="checkbox" checked={english} onChange={(e) => setEnglish(e.target.checked)} />
                      Show translation</label>
                  )}
                </div>
                {lines ? (
                  <div className="transcript recap">
                    {lines.map((l, i) => (
                      <div key={i} className={`bubble ${l.who}`}>
                        <span className="who">{l.who === "agent" ? "Agent" : c.farmer_name}</span>
                        <span>{l.text}</span>
                        {english && l.translation && <span className="tr">{l.translation}</span>}
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="muted">{c.status === "dropped" ? "The call dropped before it finished. Answers saved during the call are kept above."
                    : c.consent === false ? "No transcript: the farmer did not agree to one being kept." : "No transcript for this call."}</p>
                )}
              </section>
            </div>
          </>}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}
