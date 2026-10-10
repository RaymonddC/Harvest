import { useEffect, useState } from "react";
import { api, cropLabel, plainPrice } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import StepTop from "./StepTop.jsx";

const FIELDS = ["floor_price", "reference_price", "ceiling_price", "first_premium_pct", "step_pct"];

// The rungs the agent offers in order, from the form's current (maybe unsaved) values.
function ladder(f, l) {
  const v = (k) => Number(f[k]);
  const floor = v("floor_price"), ref = v("reference_price"), ceil = v("ceiling_price");
  if (!(floor > 0 && floor <= ref && ref <= ceil) || v("step_pct") <= 0) return null;
  const inc = l.price_increment || 0.01;
  const round = (p) => Math.round(p / inc) * inc;
  const rungs = [];
  for (let p = ref * (1 + v("first_premium_pct") / 100); round(p) < ceil && rungs.length < 30; p += ref * v("step_pct") / 100) {
    const r = Math.max(round(p), floor);
    if (!rungs.length || r > rungs[rungs.length - 1]) rungs.push(r);
  }
  rungs.push(ceil);
  return rungs;
}

const Field = ({ label, name, form, edit, step = "any" }) => (
  <label className="field">{label}<input type="number" step={step} required value={form?.[name] ?? ""} onChange={edit(name)} /></label>
);

// Step 2: the floor, market and ceiling prices, and the offer ladder they make.
// onDirty tells the page when there are unsaved edits (the step chips show it).
export default function PriceRange({ l, onDirty }) {
  const act = useAct();
  const [form, setForm] = useState(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => { onDirty(dirty); }, [dirty, onDirty]);
  // Until the planner edits it, the form follows the saved limits.
  useEffect(() => {
    if (l && !dirty) setForm(Object.fromEntries(FIELDS.map((k) => [k, l[k]])));
  }, [l, dirty]);

  const edit = (k) => (e) => { setForm({ ...form, [k]: e.target.value }); setDirty(true); };
  const save = (e) => {
    e.preventDefault();
    const body = Object.fromEntries(FIELDS.map((k) => [k, Number(form[k])]));
    act(() => api(`/api/limits/${l.id}`, { method: "PUT", body }), () => { setDirty(false); return "Price range saved. The agent uses it from the next offer."; });
  };
  const rungs = form && l ? ladder(form, l) : null;
  const refLeft = form && Number(form.ceiling_price) > Number(form.floor_price)
    ? `${Math.min(Math.max((form.reference_price - form.floor_price) / (form.ceiling_price - form.floor_price), 0), 1) * 100}%` : "50%";
  const priced = !!l && !dirty;

  return (
    <form className="card" aria-labelledby="limits-title" onSubmit={save}>
      <StepTop n={2} done={priced} word={dirty ? "Unsaved" : priced ? "Done" : "To do"} />
      <div className="step-head"><h2 id="limits-title">Fair price range</h2>
        <span className="sub">{l ? `${cropLabel(l.crop)}, ${l.currency} per ${l.unit}. The agent can only offer inside this range, and farmers are never offered less than the lowest price.` : "The agent can only offer inside this range."}</span></div>
      <div className="grid3">
        <Field label="Lowest" name="floor_price" form={form} edit={edit} />
        <Field label="Market today" name="reference_price" form={form} edit={edit} />
        <Field label="Highest" name="ceiling_price" form={form} edit={edit} />
      </div>
      <div className="range" aria-hidden="true"><div className="rail" /><div className="knob lo" /><div className="ref" style={{ left: refLeft }} /><div className="knob hi" /></div>
      <span className="sub">{l && l.reference_source ? `Market price source: ${l.reference_source}` : ""}</span>
      <details>
        <summary>How the agent climbs the offer</summary>
        <div className="grid2" style={{ marginTop: 10 }}>
          <Field label="First offer, % over market" name="first_premium_pct" form={form} edit={edit} step="0.5" />
          <Field label="Each step, % of market" name="step_pct" form={form} edit={edit} step="0.5" />
        </div>
        <p className="sub" style={{ margin: "10px 0 6px" }}>The agent offers these in order when asked for a better price:</p>
        <div className="ladder">
          {rungs ? rungs.map((p) => <span key={p} className="num">{plainPrice(p, l.currency)}</span>) : form && <span>Needs floor ≤ reference ≤ ceiling.</span>}
        </div>
      </details>
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginTop: "auto" }}>
        <button className="btn solid" type="submit" disabled={!l}>Save price range</button>
        <span className="small muted">Illustrative prices for the demo.</span>
      </div>
    </form>
  );
}
