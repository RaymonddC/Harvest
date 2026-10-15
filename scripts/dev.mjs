// `npm start` at the repo root: the backend (port 8000) and the React dashboard (port 5173)
// together, in one terminal. Ctrl+C stops everything. No packages to install.
//
//   npm start            in-memory demo data, ignores .env (safe default)
//   npm run start:env    reads .env too (repo root or backend/): Gemini credentials, other settings
//   npm run start:phone  real phone calls from your PC: reads .env, opens a Cloudflare quick tunnel so
//                        Twilio can reach the backend, sets PUBLIC_BASE_URL to it, and fetches a fresh
//                        VERTEX_ACCESS_TOKEN from gcloud. Needs cloudflared and a signed-in gcloud.
import { spawn, execSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const phone = process.argv.includes("--phone");
const useDotenv = phone || process.argv.includes("--env");
const win = process.platform === "win32";
const python = process.env.PYTHON || (win ? "python" : "python3");

const children = [];
let stopping = false;

function stopAll(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const c of children) {
    if (c.exitCode !== null) continue;
    if (win) spawn("taskkill", ["/pid", String(c.pid), "/t", "/f"], { stdio: "ignore" });
    else c.kill("SIGTERM");
  }
  setTimeout(() => process.exit(code), 500);
}

// Starts one process with its output prefixed; onLine sees every line (used to find the tunnel URL).
function run({ name, color, cmd, args, cwd = root, env = {}, onLine }) {
  // npm and gcloud are .cmd files on Windows, which need a shell; give the shell one command line
  // (the args are fixed, no user input). A path with spaces is quoted.
  const quoted = cmd.includes(" ") ? `"${cmd}"` : cmd;
  const child = win
    ? spawn([quoted, ...args].join(" "), { cwd, env: { ...process.env, ...env }, shell: true })
    : spawn(cmd, args, { cwd, env: { ...process.env, ...env } });
  const prefix = `${color}[${name}]\x1b[0m `;
  const pipe = (stream, out) => {
    let buf = "";
    stream.on("data", (d) => {
      buf += d.toString();
      const lines = buf.split(/\r?\n/);
      buf = lines.pop();
      for (const line of lines) {
        out.write(prefix + line + "\n");
        onLine?.(line);
      }
    });
  };
  pipe(child.stdout, process.stdout);
  pipe(child.stderr, process.stderr);
  child.on("exit", (code) => {
    if (!stopping) {
      console.error(`${prefix}stopped (exit ${code}); stopping the others too.`);
      stopAll(code || 1);
    }
  });
  children.push(child);
  return child;
}

function findCloudflared() {
  const candidates = [
    process.env.CLOUDFLARED,
    "C:\\Program Files (x86)\\cloudflared\\cloudflared.exe",
    "C:\\Program Files\\cloudflared\\cloudflared.exe",
  ].filter(Boolean);
  for (const c of candidates) if (existsSync(c)) return c;
  try {
    execSync(win ? "where cloudflared" : "command -v cloudflared", { stdio: "ignore" });
    return "cloudflared";
  } catch {
    return null;
  }
}

function vertexToken() {
  try {
    return execSync("gcloud auth print-access-token", { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
  } catch {
    return null;
  }
}

// The tunnel prints its public address once it is up; wait for it (or give up after a minute).
function openTunnel() {
  const exe = findCloudflared();
  if (!exe) {
    console.error("cloudflared not found. Install it: winget install --id Cloudflare.cloudflared -e");
    process.exit(1);
  }
  return new Promise((resolveUrl) => {
    const timer = setTimeout(() => { console.error("The tunnel did not start within 60 s."); stopAll(1); }, 60_000);
    run({
      name: "tunnel  ", color: "\x1b[35m", cmd: exe, args: ["tunnel", "--no-autoupdate", "--url", "http://localhost:8000"],
      onLine: (line) => {
        const m = line.match(/https:\/\/[a-z0-9-]+\.trycloudflare\.com/);
        if (m) { clearTimeout(timer); resolveUrl(m[0]); }
      },
    });
  });
}

const backendEnv = useDotenv ? {} : { HARVEST_NO_DOTENV: "1" };
let publicUrl = null;

if (phone) {
  const token = vertexToken();
  if (token) backendEnv.VERTEX_ACCESS_TOKEN = token;
  else console.error("Could not get a Vertex token from gcloud (run: gcloud auth login). The voice agent will not connect.");
  publicUrl = await openTunnel();
  backendEnv.PUBLIC_BASE_URL = publicUrl;
}

run({
  name: "backend ", color: "\x1b[32m", cmd: python,
  // No --reload in phone mode: a reload would drop a live call and wipe the in-memory data.
  args: ["-m", "uvicorn", "app.main:app", "--port", "8000", ...(phone ? [] : ["--reload"])],
  cwd: resolve(root, "backend"), env: backendEnv,
});
run({ name: "frontend", color: "\x1b[36m", cmd: "npm", args: ["run", "dev"], cwd: resolve(root, "frontend") });

console.log(`\nHarvest-Call: dashboard http://localhost:5173  (sign in: dewi / harvest-demo)`);
console.log(`               call page http://localhost:5173/call.html`);
if (phone) {
  console.log(`               phone calls: ON, Twilio reaches the backend at ${publicUrl}`);
  console.log(`               Vertex token is valid for about 1 hour; restart to refresh it.`);
  console.log(`               Setup -> edit a farmer's phone to your number -> ... -> Call by phone`);
} else {
  console.log(`               ${useDotenv ? "using .env" : "demo data, .env ignored (npm run start:env to use it)"}`);
}
console.log(`               Ctrl+C stops everything.\n`);

process.on("SIGINT", () => stopAll(0));
process.on("SIGTERM", () => stopAll(0));
