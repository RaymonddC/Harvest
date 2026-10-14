// Runs the stand-in farmer's line chooser over what the agent really said in recorded calls.
// Usage: node stand_in_check.mjs <farmer-lines.json> <stand-in.js>   (prints a JSON list of the chosen line ids)
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const lines = JSON.parse(readFileSync(process.argv[2], "utf8"));
const { pickLine } = await import(pathToFileURL(process.argv[3]).href);
const flows = JSON.parse(readFileSync(0, "utf8"));  // {name: [agent turns]}
const out = {};
for (const [name, turns] of Object.entries(flows)) {
  const used = {};
  out[name] = turns.map((t) => {
    const i = pickLine(lines, t, used);
    if (i < 0) return null;
    used[lines[i].id] = (used[lines[i].id] || 0) + 1;
    return lines[i].id;
  });
}
console.log(JSON.stringify(out));
