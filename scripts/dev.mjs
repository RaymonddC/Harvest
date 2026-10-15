// `npm start` at the repo root: the backend (port 8000) and the React dashboard (port 5173)
// together, in one terminal. Ctrl+C stops both. No packages to install.
//
//   npm start          in-memory demo data, ignores backend/.env (safe default)
//   npm run start:env  reads backend/.env too (Gemini credentials, other settings)
import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const useDotenv = process.argv.includes("--env");
const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");

const procs = [
  {
    name: "backend ",
    color: "\x1b[32m",
    cmd: python,
    args: ["-m", "uvicorn", "app.main:app", "--port", "8000", "--reload"],
    cwd: resolve(root, "backend"),
    env: useDotenv ? {} : { HARVEST_NO_DOTENV: "1" },
  },
  {
    name: "frontend",
    color: "\x1b[36m",
    cmd: "npm",
    args: ["run", "dev"],
    cwd: resolve(root, "frontend"),
    env: {},
  },
];

const children = [];
let stopping = false;

function stopAll(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const c of children) {
    if (c.exitCode !== null) continue;
    if (process.platform === "win32") spawn("taskkill", ["/pid", String(c.pid), "/t", "/f"], { stdio: "ignore" });
    else c.kill("SIGTERM");
  }
  setTimeout(() => process.exit(code), 500);
}

for (const p of procs) {
  // npm is npm.cmd on Windows, which needs a shell; give the shell one command line (the args are fixed, no user input).
  const win = process.platform === "win32";
  const child = win
    ? spawn([p.cmd, ...p.args].join(" "), { cwd: p.cwd, env: { ...process.env, ...p.env }, shell: true })
    : spawn(p.cmd, p.args, { cwd: p.cwd, env: { ...process.env, ...p.env } });
  const prefix = `${p.color}[${p.name}]\x1b[0m `;
  const pipe = (stream, out) => {
    let buf = "";
    stream.on("data", (d) => {
      buf += d.toString();
      const lines = buf.split(/\r?\n/);
      buf = lines.pop();
      for (const line of lines) out.write(prefix + line + "\n");
    });
  };
  pipe(child.stdout, process.stdout);
  pipe(child.stderr, process.stderr);
  child.on("exit", (code) => {
    if (!stopping) {
      console.error(`${prefix}stopped (exit ${code}); stopping the other one too.`);
      stopAll(code || 1);
    }
  });
  children.push(child);
}

console.log(`\nHarvest-Call: dashboard http://localhost:5173  (sign in: dewi / harvest-demo)`);
console.log(`               call page http://localhost:5173/call.html`);
console.log(`               ${useDotenv ? "using backend/.env" : "demo data, backend/.env ignored (npm run start:env to use it)"}`);
console.log(`               Ctrl+C stops both.\n`);

process.on("SIGINT", () => stopAll(0));
process.on("SIGTERM", () => stopAll(0));
