import { useEffect, useState } from "react";
import { api } from "../../lib.js";
import { Icon } from "../../ui.jsx";

// Why the gap week is short: the note built from call answers, replaced by Gemini's wording
// when the backend has one.
export default function GapNote({ gap }) {
  const [polished, setPolished] = useState(null);
  const key = gap && gap.note ? `${gap.week}:${gap.note}` : "";
  useEffect(() => {
    setPolished(null);
    if (!key) return undefined;
    let live = true;
    api("/api/forecast/summary", { method: "GET" }).then((r) => {
      if (live && `${r.gap_week}` === `${gap.week}` && r.gap_note) setPolished(r);
    }).catch(() => {});
    return () => { live = false; };
  }, [key]);
  if (!key) return null;
  const by = polished && polished.gap_note_by === "gemini" ? "Note drafted by Gemini." : "Note built from today's call answers.";
  return (
    <div className="note" id="gap-note">
      <span className="spark"><Icon name="spark" size={15} /></span>
      <div><strong style={{ display: "block" }}>Why week {gap.week} is short</strong>{polished ? polished.gap_note : gap.note} <span className="muted">{by}</span></div>
    </div>
  );
}
