// Picks which scripted farmer line answers what the agent just said ("Play the farmer for me").
// A line is {text, audio, id, when?, after?, max?, ends?, fallback?}:
//   when      regular expression (case-insensitive) matched against the agent's last turn
//   after     id of a line that must already have been said (keeps the story in order: a price word in the
//             greeting cannot trigger the counter-offer)
//   max       how many times it may be said (default 1)
//   ends      the stand-in switches itself off after this line (the goodbye)
//   fallback  said when nothing else fits (a short yes), a few times at most
// Lines are tried in file order, so earlier lines win when several match.

export function pickLine(lines, agentText, used) {
  const said = (id) => (used[id] || 0) > 0;
  const left = (l) => (used[l.id] || 0) < (l.max ?? 1);
  const text = String(agentText || "");
  const hit = lines.findIndex((l) => !l.fallback && l.when && left(l) && (!l.after || said(l.after)) && new RegExp(l.when, "i").test(text));
  if (hit >= 0) return hit;
  return lines.findIndex((l) => l.fallback && left(l));
}
