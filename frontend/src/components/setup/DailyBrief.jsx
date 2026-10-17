import { api, can } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { ActButton } from "../../ui.jsx";

// Gemini's daily brief (backend daily_brief.py): a few sentences on the last 24 hours and what it changed in the task
// list. The hourly job writes it once a day from 07:00; a planner can write it now. Its tasks live on the farmers'
// cards and show in "What to do next" when due.
const day = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "short" });

export default function DailyBrief({ state, onOpen }) {
  const act = useAct();
  const brief = [...(state.briefs || [])].sort((a, b) => (b.date || "").localeCompare(a.date || ""))[0];
  const farmers = new Map((state.farmers || []).map((f) => [f.id, f]));
  const write = () => act(() => api("/api/brief", { body: {} }),
    (r) => `Brief written${r.tasks_added?.length ? `; ${r.tasks_added.length} new task${r.tasks_added.length > 1 ? "s" : ""}` : ""}.`);
  return (
    <section className="card brief-card" aria-labelledby="brief-title">
      <div className="card-head">
        <div>
          <h2 id="brief-title">Daily brief</h2>
          <span className="sub">{brief ? `${day(brief.date)}, written by Gemini` : "Gemini sums up each day at 07:00 and keeps the task list up to date."}</span>
        </div>
        {can("campaign.run") && <ActButton className="btn sm" busy="Writing…" run={write}>{brief ? "Write it again" : "Write today’s brief"}</ActButton>}
      </div>
      {brief ? (
        <>
          <p className="brief-text">{brief.summary}</p>
          {(brief.tasks_added?.length > 0 || brief.tasks_done?.length > 0) && (
            <ul className="brief-tasks">
              {brief.tasks_added?.map((t) => (
                <li key={t.id}>
                  <button type="button" className="linkish" onClick={() => farmers.get(t.farmer_id) && onOpen?.(farmers.get(t.farmer_id))}>{t.name}</button>
                  <span>{t.text}</span>
                  <small className="muted">by {new Date(`${t.due}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}</small>
                </li>
              ))}
              {brief.tasks_done?.map((t) => (
                <li key={t.id} className="done"><b>{t.name}</b><span>{t.text}</span><small className="muted">done</small></li>
              ))}
            </ul>
          )}
        </>
      ) : <p className="small muted" style={{ margin: 0 }}>No brief yet.</p>}
    </section>
  );
}
