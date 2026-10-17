import { useCrop } from "../campaigns.jsx";
import AgentCard from "../components/setup/AgentCard.jsx";
import { DownloadLink } from "../ui.jsx";
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
      <DownloadLink path="/api/answers.csv" filename="answers.csv">Download answers</DownloadLink>
    </div>
  );
  return (
    <Shell title="Agent" head={head}>
      {state && <AgentCard key={cid} state={state} cid={cid} />}
    </Shell>
  );
}
