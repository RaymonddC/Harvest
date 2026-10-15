import { useNavigate } from "react-router-dom";
import { campaignFor, cropName, useCrop } from "../../campaigns.jsx";
import { api, cfg } from "../../lib.js";
import { useAct } from "../../toast.jsx";
import { ActButton, Icon } from "../../ui.jsx";
import StepTop from "./StepTop.jsx";

// Step 3: what the campaign will do, and the button that starts (or stops) it.
export default function StartCalling({ state, toCall }) {
  const act = useAct();
  const navigate = useNavigate();
  const { crop } = useCrop();
  const campaign = campaignFor(state, crop);
  const running = campaign.status === "running";
  const s = state.settings || {};
  const minutes = Math.round((s.max_call_seconds || 360) / 60);
  const retries = Math.max((s.max_call_attempts || 2) - 1, 0);
  const phoneCalls = !!s.phone_calls;
  const byPhone = campaign.channel === "twilio";
  // channel "twilio" rings the farmers' real phones, one at a time; "browser" queues demo calls for the call client.
  const start = async (channel) => {
    const r = await act(() => api("/api/campaign/start", { body: { kind: "collect", crop, channel } }),
      channel === "twilio" ? (x) => `Calling phones: ${x.queued} farmers, one at a time.` : null);
    if (r) navigate("/");
  };
  return (
    <section className="card dark" aria-labelledby="campaign-title">
      <StepTop n={3} done={false} word={running ? "Calling" : toCall ? "Ready" : "Waiting"} cls={running ? "leaf" : ""} />
      <div className="step-head"><h2 id="campaign-title">Start calling</h2>
        <span className="sub">The agent asks every farmer about weeks 1 to {s.weeks || 5}, in {s.language || cfg.language || "the configured language"}.</span></div>
      <div className="stats" id="campaign-lines">
        <div><b>{toCall}</b><span>{toCall === 1 ? "farmer" : "farmers"}</span></div>
        <div><b>≤ {minutes} min</b><span>per call</span></div>
        <div><b>{retries === 1 ? "1 retry" : `${retries} retries`}</b><span>if dropped</span></div>
      </div>
      <span className="small" style={{ color: "var(--on-ink-muted)" }}>Nothing is agreed without your approval.</span>
      <span className="small" style={{ color: "var(--on-ink-muted)" }}>
        {phoneCalls ? s.phone_calls_note : "Demo mode: calls are answered in the browser call page."}
      </span>
      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: "auto" }}>
        {running ? <>
          <span className="pill lg dot running" style={{ alignSelf: "flex-start", background: "var(--ink-2)", color: "var(--on-ink)" }}>{byPhone ? "Calling phones, one at a time" : campaign.kind === "gap_fill" ? "Gap-fill calls running" : "Calling farmers now"}</span>
          {byPhone
            ? <a className="btn mint big block" href="/">Watch the calls</a>
            : <a className="btn mint big block" href="/call.html" target="_blank" rel="noopener">Open call client</a>}
          <ActButton need="campaign.run" className="btn on-ink block" busy="Stopping…" run={() => act(() => api("/api/campaign/stop", { body: { crop } }), "Calling stopped.")}>Stop calling</ActButton>
        </> : phoneCalls ? <>
          <ActButton need="campaign.run" className="btn mint big block" busy="Starting…" disabled={!toCall} run={() => start("twilio")}>
            <Icon name="phone" />{toCall ? `Call ${toCall} ${cropName(crop)} ${toCall === 1 ? "farmer's phone" : "farmers' phones"}` : "Add farmers to start"}
          </ActButton>
          <ActButton need="campaign.run" className="btn on-ink block" busy="Starting…" disabled={!toCall} run={() => start("browser")}>Demo in the browser</ActButton>
        </> : (
          <ActButton need="campaign.run" className="btn mint big block" busy="Starting…" disabled={!toCall} run={() => start("browser")}>
            <Icon name="phone" />{toCall ? `Start calling ${toCall} ${cropName(crop)} ${toCall === 1 ? "farmer" : "farmers"}` : "Add farmers to start"}
          </ActButton>
        )}
      </div>
    </section>
  );
}
