import { maskPhone } from "../../lib.js";
import { Pill } from "../../ui.jsx";

const KIND = { deal_confirmation: "Deal confirmation", gap_alert: "Gap alert", offer_waiting: "Offer waiting", offers_digest: "Monday digest", test: "Test" };
const STATUS = { sent: ["Sent", "mint"], failed: ["Failed", "danger"], not_sent: ["Not sent", ""] };
const when = (iso) => (iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");

// The outbox: written deal confirmations to farmers and alerts to the planner, with what happened to each.
export default function Messages({ state }) {
  const list = [...(state.messages || [])].sort((a, b) => (b.created_at || "").localeCompare(a.created_at || "")).slice(0, 8);
  return (
    <section className="card messages-card" aria-labelledby="msg-title">
      <h3 id="msg-title">Messages</h3>
      <p className="small muted">{state.settings?.messaging_note}</p>
      {list.length ? (
        <ul className="msg-list">
          {list.map((m) => {
            const [word, cls] = STATUS[m.status] || [m.status, ""];
            return (
              <li key={m.id}>
                <div className="msg-head">
                  <span className="label">{KIND[m.kind] || m.kind} · {m.audience === "planner" ? "to the planner" : m.farmer_name || "farmer"}{m.to ? ` (${maskPhone(m.to)})` : ""}</span>
                  <Pill cls={cls}>{word}</Pill>
                </div>
                <p className="msg-body">{m.body}</p>
                <span className="small muted">{when(m.created_at)}{m.reason ? ` · ${m.reason}` : ""}</span>
              </li>
            );
          })}
        </ul>
      ) : <p className="muted">No messages yet. Deal confirmations and planner alerts appear here.</p>}
    </section>
  );
}
