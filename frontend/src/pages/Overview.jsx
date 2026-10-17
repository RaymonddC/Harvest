import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Link } from "react-router-dom";
import { campaignFor, inCampaign, useCrop } from "../campaigns.jsx";
import TargetBreakdown, { breakdown } from "../components/forecast/TargetBreakdown.jsx";
import FarmerPipeline from "../components/setup/FarmerPipeline.jsx";
import FarmerForm from "../components/setup/FarmerForm.jsx";
import FarmerSheet from "../components/setup/FarmerSheet.jsx";
import { farmersBehind } from "../components/setup/NeedPanel.jsx";
import { crmOf, toCallOf } from "../crm.js";
import { fmtT } from "../lib.js";
import { useLive } from "../live.jsx";
import Shell from "../Shell.jsx";
import { nextAutoText, todoItems } from "../todo.js";
import { Icon } from "../ui.jsx";

// The campaign at a glance, everything connected:
//   1. the chain from farmers to deliveries, with a count at every link (where the work stands)
//   2. what we have and what we lack against the target, in total and per week (click a part: its farmers)
//   3. what to do next, most urgent first
//   4. the farmers as a pipeline board
export default function Overview() {
  const { state } = useLive();
  const { cid } = useCrop();
  const [filter, setFilter] = useState(null);
  const [openFarmer, setOpenFarmer] = useState(null);
  const [farmerForm, setFarmerForm] = useState(null);
  const campaign = state ? campaignFor(state, cid) : {};
  const rows = state ? inCampaign(state, state.forecast, cid).sort((a, b) => a.week - b.week) : [];
  const supply = state ? toCallOf(state, cid) : { unknown: [], usualKg: 0 };
  const data = breakdown(rows.filter((r) => !r.before_start), supply.usualKg);
  const sum = (k) => data.reduce((n, d) => n + d[k], 0);
  const target = sum("target_kg");
  const have = sum("there");
  const parts = [
    { key: "there", label: "We have", kg: have, note: "answers saved and approved deals", cls: "tb-there" },
    { key: "waiting", label: "Waiting for you", kg: sum("waiting"), note: "offers to approve", cls: "tb-waiting" },
    { key: "unknown", label: "Not answered yet", kg: sum("unknown"), note: `${supply.unknown.length} farmers, their usual supply`, cls: "tb-unknown" },
    { key: "missing", label: "We still lack", kg: sum("missing"), note: "to add: gap-fill calls or a supplier", cls: "tb-missing" },
  ];
  const crm = state ? crmOf(state, cid) : { farmers: [], counts: {} };
  const c = crm.counts;
  const offersKg = state ? inCampaign(state, state.offers, cid).filter((o) => ["pending", "escalated"].includes(o.status)).reduce((n, o) => n + o.kg, 0) : 0;
  const deals = state ? inCampaign(state, state.offers, cid).filter((o) => o.status === "approved") : [];
  // Where the campaign's farmers stand, left to right. "bar" is how many farmers sit in that stage now (the strip on
  // top); the figure under each label is what that stage holds in tonnes.
  const chain = [
    { key: "call", label: "Need a call", n: (c.to_call || 0) + (c.no_reply || 0) + (c.calling || 0), sub: "no current answer", to: "/setup#farmer-list", warn: true },
    { key: "answered", label: "Answered", n: c.answered || 0, sub: `${fmtT(have)} t counted`, to: "/forecast" },
    { key: "offer", label: "Offers", n: c.offer || 0, sub: `${fmtT(offersKg)} t waiting`, to: "/approvals", warn: (c.offer || 0) > 0 },
    { key: "deal", label: "Deals", n: c.deal || 0, sub: `${fmtT(deals.reduce((n, o) => n + o.kg, 0))} t agreed`, to: "/approvals" },
    { key: "delivered", label: "Delivered", n: c.delivered || 0, sub: `${fmtT(deals.reduce((n, o) => n + (o.delivered_kg || 0), 0))} t in`, to: "/forecast" },
  ];
  const total = Math.max(1, crm.farmers.length);
  const items = todoItems(state, cid);
  const pick = (f) => { setFilter(f); setTimeout(() => document.getElementById("farmer-list")?.scrollIntoView({ block: "start", behavior: "smooth" }), 50); };

  const head = (
    <div className="page-head">
      <div>
        <h1>Overview{campaign.label ? <span className="h1-ctx">{campaign.label}</span> : null}</h1>
        <p>What we have, what we lack, and what to do next. Every number links to where it comes from.</p>
      </div>
    </div>
  );
  return (
    <Shell title="Overview" head={head}>
      {state && (
        <>
          <section className="card chain-card" aria-labelledby="chain-title">
            <div className="chain-top">
              <h2 id="chain-title"><Link to="/setup#farmer-list">{crm.farmers.length} farmers</Link> in this campaign</h2>
              <span className="small muted">where each one stands</span>
            </div>
            <div className="chain-bar" aria-hidden="true">
              {chain.filter((s) => s.n).map((s) => <span key={s.key} className={`cb-${s.key}`} style={{ flexGrow: s.n }} title={`${s.label}: ${s.n}`} />)}
            </div>
            <ol className="chain">
              {chain.map((s) => (
                <li key={s.key} className={`cb-${s.key} ${s.warn && s.n ? "warn" : ""}`}>
                  <Link to={s.to}>
                    <span className="ch-label"><i aria-hidden="true" />{s.label}</span>
                    <span className="ch-n num">{s.n}<small> of {total}</small></span>
                    <small>{s.sub}</small>
                  </Link>
                </li>
              ))}
            </ol>
          </section>

          <div className="ov-grid">
            <section className="card" aria-labelledby="have-title">
              <div className="card-head">
                <div>
                  <h2 id="have-title" className="have-say"><b className="num">{fmtT(have)} t</b> of the {fmtT(target)} t target is in hand</h2>
                  <span className="sub">Next {data.length} weeks. {sum("missing") > 0 ? `${fmtT(sum("missing"))} t still has to be found` : "Nothing left to find"}{sum("unknown") > 0 ? `, and about ${fmtT(sum("unknown"))} t more should come once ${supply.unknown.length} farmers answer.` : "."}</span>
                </div>
                <Link className="btn sm" to="/forecast">Live forecast</Link>
              </div>
              <div className="have-bar" role="img" aria-label={parts.map((p) => `${p.label} ${fmtT(p.kg)} t`).join(", ")}>
                {parts.map((p) => p.kg > 0 && <i key={p.key} className={p.cls} style={{ flexGrow: p.kg }} />)}
              </div>
              <dl className="have-ledger">
                {parts.map((p) => (
                  <div key={p.key} className={p.key}>
                    <dt><i className={p.cls} />{p.label}</dt>
                    <dd><b className="num">{fmtT(p.kg)} t</b><small>{p.note}</small></dd>
                  </div>
                ))}
              </dl>
              <TargetBreakdown rows={rows} unknownKg={supply.usualKg} compact onPick={(d, part) => pick(farmersBehind(state, cid, d, part, supply.unknown))} />
            </section>

            <section className="card todo-card" aria-labelledby="todo-title">
              <h2 id="todo-title">What to do next</h2>
              {items.length ? (
                <ol className="todo-list">
                  <AnimatePresence initial={false}>
                    {items.map((it) => (
                      <motion.li key={it.key} className={it.tone} layout initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.22, ease: [0.2, 0.8, 0.2, 1] }}>
                        <div><b>{it.what}</b><small>{it.next}</small></div>
                        <Link className="btn sm" to={it.to}>{it.verb || "Open"}</Link>
                      </motion.li>
                    ))}
                  </AnimatePresence>
                </ol>
              ) : (
                <p className="todo-done"><motion.span className="done-mark" initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}
                  transition={{ type: "spring", duration: 0.5, bounce: 0.25 }}><Icon name="check" size={18} /></motion.span> Nothing waiting: every week is on track and every farmer has answered{nextAutoText(campaign) ? `; ${nextAutoText(campaign)}` : ""}.</p>
              )}
            </section>
          </div>

          <FarmerPipeline state={state} cid={cid} title="Farmers, by stage" filter={filter} onClearFilter={() => setFilter(null)}
            onEdit={setFarmerForm} onOpen={setOpenFarmer} />
          <FarmerSheet farmer={openFarmer} state={state} onClose={() => setOpenFarmer(null)} />
          <FarmerForm farmer={farmerForm} onClose={() => setFarmerForm(null)} />
        </>
      )}
    </Shell>
  );
}
