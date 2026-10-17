import { useEffect, useState } from "react";
import { useConfirm } from "../../dialogs.jsx";
import { api, cachedGet, can, fmtT, peekGet } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { ActButton } from "../../ui.jsx";
import { shortDate } from "./Chart.jsx";

const later = (iso, days) => { const d = new Date(`${iso}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0, 10); };

// A week with more fruit than the mill can press: palm fruit spoils within a day or two, so the extra has to come
// later. Lists the farmers whose harvest falls in that week (biggest first) with "Move a week later".
export default function SurplusCard({ row, cid }) {
  const act = useAct();
  const confirm = useConfirm();
  const url = `/api/surplus?week=${row.week}&campaign=${encodeURIComponent(cid)}`;
  const [list, setList] = useState(() => peekGet(url)?.farmers || null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    cachedGet(url).then((r) => { if (live) setList(r.farmers); }).catch(() => {});
    return () => { live = false; };
  }, [row.week, row.expected_kg, cid, tick]);
  const move = async (f) => {
    const to = later(f.ready_date, 7);
    if (await confirm({ title: `Move ${f.name} a week later?`, body: `Agree it with the farmer first. Their ${fmtT(f.kg)} t moves from ${shortDate(f.ready_date)} to ${shortDate(to)}, and they get a text with the new date.`, confirm: "Move a week later" })) {
      const r = await act(() => api(`/api/farmers/${f.farmer_id}/reschedule`, { body: { to_date: to, reason: `week ${row.week} over the mill's capacity` } }),
        `${f.name} now delivers from ${shortDate(to)}.`);
      if (r) setTick((n) => n + 1);
    }
  };
  let left = row.surplus_kg;
  return (
    <section className="card surplus-card" aria-labelledby="surplus-title">
      <div className="card-head">
        <h2 id="surplus-title">Week {row.week} is {fmtT(row.surplus_kg)} t over capacity</h2>
      </div>
      <p className="small muted" style={{ margin: 0 }}>
        {fmtT(row.expected_kg)} t expected, the mill presses {fmtT(row.capacity_kg)} t that week. Palm fruit spoils within a day or two, so ask some farmers to harvest a week later.
      </p>
      {list === null ? null : list.length ? (
        <ul className="rows">
          {list.slice(0, 6).map((f) => {
            const enough = left <= 0;
            left -= f.kg;
            return (
              <li key={f.farmer_id} className={`row ${enough ? "muted" : ""}`}>
                <span className="name">{f.name}<small className="muted">{f.village} · {fmtT(f.kg)} t on {shortDate(f.ready_date)}</small></span>
                {can("farmers.manage") && <ActButton className="btn sm" busy="Moving…" run={() => move(f)}>A week later</ActButton>}
              </li>
            );
          })}
        </ul>
      ) : <p className="small muted">No farmer's harvest in that week can be moved (approved deals stay where they are).</p>}
    </section>
  );
}
