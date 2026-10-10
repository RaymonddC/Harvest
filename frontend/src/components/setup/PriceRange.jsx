import * as Slider from "@radix-ui/react-slider";
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

// Lowest, market and highest price on one track. Drag a knob (or use the arrow keys) and the
// boxes above follow; type in a box and the knob moves. The track spans a fifth below the saved
// floor to a fifth above the saved ceiling, so it stays put while dragging.
function PriceSlider({ form, l, onChange }) {
  const inc = l.price_increment || 10;
  const span = l.ceiling_price - l.floor_price || l.reference_price * 0.2;
  const lo = Math.max(0, Math.floor((l.floor_price - span) / inc) * inc);
  const hi = Math.ceil((l.ceiling_price + span) / inc) * inc;
  const v = ["floor_price", "reference_price", "ceiling_price"].map((k) => Math.min(Math.max(Number(form[k]) || 0, lo), hi));
  const names = ["Lowest price", "Market price today", "Highest price"];
  return (
    <div className="price-slider">
      <Slider.Root className="ps-root" min={lo} max={hi} step={inc} value={v} minStepsBetweenThumbs={0}
        onValueChange={([floor, ref, ceil]) => onChange({ floor_price: floor, reference_price: ref, ceiling_price: ceil })}>
        <Slider.Track className="ps-track"><Slider.Range className="ps-range" /></Slider.Track>
        {names.map((n, i) => <Slider.Thumb key={n} className={`ps-thumb ${i === 1 ? "ref" : ""}`} aria-label={n} />)}
      </Slider.Root>
      <div className="ps-scale" aria-hidden="true"><span>{plainPrice(lo, l.currency)}</span><span>{plainPrice(hi, l.currency)}</span></div>
    </div>
  );
}

const Field = ({ label, name, form, edit, step = "any" }) => (
  <label className="field">{label}<input type="number" step={step} required value={form?.[name] ?? ""} onChange={edit(name)} /></label>
);

// Step 2: the floor, market and ceiling prices, and the offer ladder they make.
export default function PriceRange({ l }) {
  const act = useAct();
  const [form, setForm] = useState(null);
  const [dirty, setDirty] = useState(false);
  // Until the planner edits it, the form follows the saved limits.
  useEffect(() => {
    if (l && !dirty) setForm(Object.fromEntries(FIELDS.map((k) => [k, l[k]])));
  }, [l, dirty]);

  const edit = (k) => (e) => { setForm({ ...form, [k]: e.target.value }); setDirty(true); };
  const slide = (values) => { setForm({ ...form, ...values }); setDirty(true); };
  const save = (e) => {
    e.preventDefault();
    const body = Object.fromEntries(FIELDS.map((k) => [k, Number(form[k])]));
    act(() => api(`/api/limits/${l.id}`, { method: "PUT", body }), () => { setDirty(false); return "Price range saved. The agent uses it from the next offer."; });
  };
  const rungs = form && l ? ladder(form, l) : null;
  const priced = !!l && !dirty;

  return (
    <form className={`card ${priced ? "done" : ""}`} aria-labelledby="limits-title" onSubmit={save}>
      <StepTop n={2} done={priced} word={dirty ? "Unsaved" : priced ? "Done" : "To do"} />
      <div className="step-head"><h2 id="limits-title">Fair price range</h2>
        <span className="sub">{l ? `${cropLabel(l.crop)}, ${l.currency} per ${l.unit}. The agent can only offer inside this range, and farmers are never offered less than the lowest price.` : "The agent can only offer inside this range."}</span></div>
      <div className="grid3">
        <Field label="Lowest" name="floor_price" form={form} edit={edit} />
        <Field label="Market today" name="reference_price" form={form} edit={edit} />
        <Field label="Highest" name="ceiling_price" form={form} edit={edit} />
      </div>
      {form && l && <PriceSlider form={form} l={l} onChange={slide} />}
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
