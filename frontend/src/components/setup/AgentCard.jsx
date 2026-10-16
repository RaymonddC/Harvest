import { useEffect, useState } from "react";
import { campaignFor } from "../../campaigns.jsx";
import { api, apiUrl, can } from "../../lib.js";
import { useUnsaved } from "../../dialogs.jsx";
import { useAct } from "../../toast.jsx";
import { SubmitButton } from "../../ui.jsx";

const EMPTY = { persona: { preset: "", name: "", voice: "", style: "" }, questions: [] };
const fromCampaign = (c) => ({
  persona: { ...EMPTY.persona, ...(c.persona || {}) },
  questions: (c.questions || []).map((q) => ({ ...q })),
});

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
    if (!key) return setPersona({ preset: "", name: "", voice: "", style: "" });
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
    const { preset, name, voice, style } = persona;
    const body = { persona: { preset, name, voice, style }, questions: form.questions.filter((q) => q.text.trim()) };
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
