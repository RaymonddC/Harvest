import { useNavigate } from "react-router-dom";
import { api, cfg } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { Icon } from "../../ui.jsx";
import StepTop from "./StepTop.jsx";

// Step 3: what the campaign will do, and the button that starts (or stops) it.
export default function StartCalling({ state, toCall }) {
  const act = useAct();
  const navigate = useNavigate();
  const campaign = state.campaigns.find((x) => x.id === "current") || {};
  const running = campaign.status === "running";
  const s = state.settings || {};
  const minutes = Math.round((s.max_call_seconds || 360) / 60);
  const retries = Math.max((s.max_call_attempts || 2) - 1, 0);
  const start = async () => {
    const r = await act(() => api("/api/campaign/start", { body: { kind: "collect" } }));
    if (r) navigate("/");
  };
  return (
    <section className="card dark" aria-labelledby="campaign-title">
      <StepTop n={3} done={false} word={running ? "Calling" : "Ready"} cls={running ? "leaf" : ""} />
      <div className="step-head"><h2 id="campaign-title">Start calling</h2>
        <span className="sub">The agent asks every farmer about weeks 1 to {s.weeks || 5}, in {s.language || cfg.language || "the configured language"}.</span></div>
      <div className="stats" id="campaign-lines">
        <div><b>{toCall}</b><span>{toCall === 1 ? "farmer" : "farmers"}</span></div>
        <div><b>≤ {minutes} min</b><span>per call</span></div>
        <div><b>{retries === 1 ? "1 retry" : `${retries} retries`}</b><span>if dropped</span></div>
      </div>
      <span className="small" style={{ color: "var(--on-ink-muted)" }}>Nothing is agreed without your approval.</span>
      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: "auto" }}>
        {running ? <>
          <span className="pill lg dot running" style={{ alignSelf: "flex-start", background: "var(--ink-2)", color: "var(--on-ink)" }}>{campaign.kind === "gap_fill" ? "Gap-fill calls running" : "Calling farmers now"}</span>
          <a className="btn mint big block" href="/call.html" target="_blank" rel="noopener">Open call client</a>
          <button className="btn on-ink block" onClick={() => act(() => api("/api/campaign/stop"), "Calling stopped.")}>Stop calling</button>
        </> : (
          <button className="btn mint big block" disabled={!toCall} onClick={start}>
            <Icon name="phone" />{toCall ? `Start calling ${toCall} farmers` : "Add farmers to start"}
          </button>
        )}
      </div>
    </section>
  );
}
