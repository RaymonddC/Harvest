import { Icon } from "../../ui.jsx";

// A step's number (a check once ready), its name, and its state in words.
export default function StepTop({ n, done, word, cls, label }) {
  return (
    <div className="step-top">
      <span className="step-dot">{done ? <Icon name="check" size={16} /> : n}</span>
      {label && <span className="step-label">Step {n}: {label}</span>}
      <span className={`pill ${cls ?? (done ? "mint" : "")}`}>{word}</span>
    </div>
  );
}
