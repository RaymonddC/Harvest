import { useEffect, useState } from "react";
import { campaignFor, campaignsOf, farmerCampaign } from "../../campaigns.jsx";
import { api, apiUrl, can } from "../../lib.js";
import { useUnsaved } from "../../dialogs.jsx";
import { useAct } from "../../toast.jsx";
import { SubmitButton } from "../../ui.jsx";

const EMPTY = { persona: { preset: "", name: "", voice: "", style: "", language_mode: "farmer", language: "", switch: true, also_speaks: [] }, questions: [] };
const fromCampaign = (c) => ({
  persona: { ...EMPTY.persona, ...(c.persona || {}) },
  questions: (c.questions || []).map((q) => ({ ...q })),
});

// Which language the agent speaks: each farmer's own (from their record) or one for every call, and whether it
// switches when the farmer answers in another language (to any language, or only the ones ticked).
function Languages({ persona, setPersona, languages, allowed, campaign, state }) {
  const fixed = persona.language_mode === "fixed";
  const also = persona.also_speaks || [];
  const toggle = (l) => setPersona({ also_speaks: also.includes(l) ? also.filter((x) => x !== l) : [...also, l] });
  // How the campaign's farmers split by their own language, so the planner sees what "each farmer's own" means.
  const mix = {};
  const camps = campaignsOf(state);
  for (const f of state.farmers) {
    if (f.type === "supplier" || farmerCampaign(f, camps) !== campaign.id) continue;
    mix[f.language || "Not set"] = (mix[f.language || "Not set"] || 0) + 1;
  }
  const start = fixed ? persona.language || "the chosen language" : "the farmer's own language";
  return (
    <fieldset className="agent-col agent-langs" disabled={!allowed}>
      <legend>Languages</legend>
      <label className="radio-row">
        <input type="radio" name="lang-mode" checked={!fixed} onChange={() => setPersona({ language_mode: "farmer" })} />
        <span><b>Each farmer's own language</b><small>From their record{Object.keys(mix).length ? `: ${Object.entries(mix).sort((a, b) => b[1] - a[1]).map(([l, n]) => `${n} ${l}`).join(", ")}` : ""}.</small></span>
      </label>
      <label className="radio-row">
        <input type="radio" name="lang-mode" checked={fixed} onChange={() => setPersona({ language_mode: "fixed", language: persona.language || languages[0] })} />
        <span><b>One language for every call</b>
          <select aria-label="Call language" value={persona.language || ""} disabled={!fixed || !allowed} onChange={(e) => setPersona({ language: e.target.value })}>
            {languages.map((l) => <option key={l}>{l}</option>)}
          </select>
        </span>
      </label>
      <label className="radio-row check">
        <input type="checkbox" checked={persona.switch !== false} onChange={(e) => setPersona({ switch: e.target.checked })} />
        <span><b>Switch when the farmer speaks another language</b>
          <small>{persona.switch !== false
            ? `Starts in ${start}; if the farmer answers in ${also.length ? "one of the languages ticked below" : "another language on the list"}, the agent carries on in it, prices and read-back included.`
            : `Speaks only ${start}, whatever the farmer answers in.`}</small></span>
      </label>
      {persona.switch !== false && (
        <div className="lang-chips" role="group" aria-label="Languages it may switch to">
          {languages.map((l) => (
            <button key={l} type="button" className={`chip-btn ${also.includes(l) ? "on" : ""}`} aria-pressed={also.includes(l)} onClick={() => toggle(l)}>{l}</button>
          ))}
          <small className="muted">{also.length ? `Only these ${also.length}. Speech recognition listens for them too.` : "None ticked: any language on the list."}</small>
        </div>
      )}
      <small className="muted">The opening and the consent notice use fixed, checked wording in each language. Thai, Vietnamese and Filipino wording still needs a native speaker's check.</small>
    </fieldset>
  );
}

// The campaign's agent: how it sounds (a ready-made persona, or name, voice and style) and the
// planner's own questions, which it asks on harvest calls after the harvest is confirmed.
// Answers are saved with each call (shown in its recap) and downloadable as a CSV.
export default function AgentCard({ state, cid }) {
  const act = useAct();
  const campaign = campaignFor(state, cid);
  const opts = state.settings?.agent_options || { voices: {}, styles: {}, presets: {}, question_types: {}, max_questions: 5 };
  const [form, setForm] = useState(EMPTY);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const { setUnsaved } = useUnsaved();
  useEffect(() => { setUnsaved(dirty); }, [dirty, setUnsaved]);
  useEffect(() => () => setUnsaved(false), [setUnsaved]);
  // Until the planner edits it, the form follows the saved campaign.
  const savedKey = JSON.stringify([campaign.id, campaign.persona, campaign.questions]);
  useEffect(() => { if (!dirty) setForm(fromCampaign(campaign)); }, [savedKey, dirty]); // eslint-disable-line react-hooks/exhaustive-deps

  const persona = form.persona;
  const setPersona = (patch) => { setForm({ ...form, persona: { ...persona, ...patch } }); setDirty(true); };
  const pickPreset = (key) => {
    if (!key) return setPersona({ preset: "", name: "", voice: "", style: "" });  // the languages stay as they are
    const { name = "", voice = "", style = "" } = opts.presets[key];
    return setPersona({ preset: key, name, voice, style });
  };
  const setQuestion = (i, patch) => {
    const questions = form.questions.map((q, j) => (j === i ? { ...q, ...patch } : q));
    setForm({ ...form, questions }); setDirty(true);
  };
  const addQuestion = () => { setForm({ ...form, questions: [...form.questions, { text: "", type: "text" }] }); setDirty(true); };
  const removeQuestion = (i) => { setForm({ ...form, questions: form.questions.filter((_, j) => j !== i) }); setDirty(true); };

  const save = async (e) => {
    e.preventDefault();
    const { preset, name, voice, style, language_mode, language, switch: sw, also_speaks } = persona;
    const body = { persona: { preset, name, voice, style, language_mode, language: language_mode === "fixed" ? language : "", switch: sw, also_speaks },
      questions: form.questions.filter((q) => q.text.trim()) };
    setSaving(true);
    await act(() => api(`/api/campaigns/${campaign.id}/agent`, { method: "PUT", body }),
      () => { setDirty(false); return "Agent saved. The next call uses it."; });
    setSaving(false);
  };
  const allowed = can("campaign.run");
  const full = form.questions.length >= (opts.max_questions || 5);

  if (!campaign.id) return null;
  return (
    <form className="card agent-card" aria-labelledby="agent-title" onSubmit={save}>
      <div className="step-head">
        <h2 id="agent-title">The agent</h2>
        <span className="sub">How the AI agent sounds on {campaign.label} calls, and what it asks besides the harvest. It always says it is an AI first, and prices still come only from the price range.</span>
      </div>

      <div className="agent-grid">
        <fieldset className="agent-col" disabled={!allowed}>
          <legend>Persona</legend>
          <div className="preset-row" role="radiogroup" aria-label="Ready-made persona">
            <button type="button" role="radio" aria-checked={!persona.preset} className={`chip-btn ${!persona.preset ? "on" : ""}`} onClick={() => pickPreset("")}>Custom</button>
            {Object.entries(opts.presets).map(([key, p]) => (
              <button type="button" role="radio" aria-checked={persona.preset === key} key={key}
                className={`chip-btn ${persona.preset === key ? "on" : ""}`} onClick={() => pickPreset(key)}>{p.label}</button>
            ))}
          </div>
          <label className="field">Name it introduces itself with
            <input type="text" maxLength={30} placeholder="No name (just “an AI assistant”)" value={persona.name}
              onChange={(e) => setPersona({ name: e.target.value, preset: "" })} />
          </label>
          <div className="grid2">
            <label className="field">Voice
              <select value={persona.voice} onChange={(e) => setPersona({ voice: e.target.value, preset: "" })}>
                <option value="">Default voice</option>
                {Object.entries(opts.voices).map(([v, d]) => <option key={v} value={v}>{v} · {d}</option>)}
              </select>
            </label>
            <label className="field">Speaking style
              <select value={persona.style} onChange={(e) => setPersona({ style: e.target.value, preset: "" })}>
                <option value="">Default (polite, short sentences)</option>
                {Object.entries(opts.styles).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
              </select>
            </label>
          </div>
        </fieldset>

        <Languages persona={persona} setPersona={setPersona} languages={opts.languages || []} allowed={allowed} campaign={campaign} state={state} />

        <fieldset className="agent-col" disabled={!allowed}>
          <legend>Your questions <span className="sub">({form.questions.length} of {opts.max_questions || 5})</span></legend>
          <span className="sub">Asked on harvest calls, after the harvest is confirmed and before any offer. The agent puts them in the farmer's language.</span>
          {form.questions.length === 0 && <p className="small muted">No extra questions. Add one, e.g. “Do you need fertiliser this month?”</p>}
          <ol className="question-list">
            {form.questions.map((q, i) => (
              <li key={q.id || `new-${i}`}>
                <input type="text" maxLength={200} aria-label={`Question ${i + 1}`} placeholder="Question in your own words"
                  value={q.text} onChange={(e) => setQuestion(i, { text: e.target.value })} />
                <select aria-label={`Answer type for question ${i + 1}`} value={q.type} onChange={(e) => setQuestion(i, { type: e.target.value })}>
                  {Object.entries(opts.question_types).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
                </select>
                <button type="button" className="btn sm more" aria-label={`Remove question ${i + 1}`} onClick={() => removeQuestion(i)}>×</button>
              </li>
            ))}
          </ol>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
            <button type="button" className="btn sm" onClick={addQuestion} disabled={full}>+ Add question</button>
            <a className="small" href={apiUrl("/api/answers.csv")} download="answers.csv">Download all answers (CSV)</a>
          </div>
        </fieldset>
      </div>

      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        {allowed ? <SubmitButton busy={saving} disabled={!dirty} busyText="Saving…">Save agent</SubmitButton>
          : <button type="button" className="btn solid" disabled title="Your role cannot change the agent.">Save agent</button>}
        {dirty && <button type="button" className="btn ghost" onClick={() => setDirty(false)}>Discard changes</button>}
      </div>
    </form>
  );
}
