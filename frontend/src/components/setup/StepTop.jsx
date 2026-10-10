import { Icon } from "../../ui.jsx";

// A step's number (a check once done) and its state in words.
export default function StepTop({ n, done, word, cls }) {
  return (
    <div className="step-top">
      <span className="step-dot">{done ? <Icon name="check" size={16} /> : n}</span>
      <span className={`pill ${cls ?? (done ? "mint" : "")}`}>{word}</span>
    </div>
  );
}
