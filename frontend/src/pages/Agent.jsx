import { useCrop } from "../campaigns.jsx";
import AgentCard from "../components/setup/AgentCard.jsx";
import { apiUrl } from "../lib.js";
import { useLive } from "../live.jsx";
import Shell from "../Shell.jsx";

// The agent of the picked campaign: persona (name, voice, speaking style) and the planner's own questions.
export default function Agent() {
  const { state } = useLive();
  const { cid, campaign } = useCrop();
  const head = (
    <div className="page-head">
      <div>
        <h1>The agent{campaign.label ? <span className="h1-ctx">{campaign.label}</span> : null}</h1>
        <p>Each campaign has its own agent. Pick the campaign in the sidebar to set up another.</p>
      </div>
      <a className="btn" href={apiUrl("/api/answers.csv")} download="answers.csv">Download answers</a>
    </div>
  );
  return (
    <Shell title="Agent" head={head}>
      {state && <AgentCard key={cid} state={state} cid={cid} />}
    </Shell>
  );
}
