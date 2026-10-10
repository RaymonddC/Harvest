import { cpSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const here = dirname(fileURLToPath(import.meta.url));
const web = resolve(here, "../web");
const backend = process.env.HARVEST_BACKEND || "http://localhost:8000";

// The call client (call.html) and the microphone test stay vanilla JS in web/ (B-03). They and the
// files they load, the farmer CSV template, plus config.js (written by deploy/deploy.sh) and the favicon, are copied into the build
// as they are, so one Hosting folder serves both.
const VANILLA = ["call.html", "mic-test.html", "farmers-template.csv", "config.js", "favicon.svg",
  "js/call.js", "js/data.js", "js/audio-worklets.js", "css/app.css", "css/call.css"];

function copyVanilla() {
  return {
    name: "copy-vanilla-call-client",
    apply: "build",
    closeBundle() {
      const out = resolve(here, "dist");
      for (const file of VANILLA) {
        mkdirSync(dirname(resolve(out, file)), { recursive: true });
        cpSync(resolve(web, file), resolve(out, file));
      }
    },
  };
}

export default defineConfig({
  // One page app served from the site root; Hosting rewrites every other path to index.html.
  base: "/",
  plugins: [react(), copyVanilla()],
  server: {
    port: 5173,
    fs: { allow: [resolve(here, "..")] },
    // In development the backend serves the API, config.js and the vanilla call client.
    proxy: Object.fromEntries(["/api", "/config.js", "/call.html", "/mic-test.html", "/farmers-template.csv", "/js", "/css", "/favicon.svg"]
      .map((p) => [p, { target: backend, changeOrigin: true }])
      .concat([["/ws", { target: backend.replace(/^http/, "ws"), ws: true }]])),
  },
  build: {
    rollupOptions: {
      input: resolve(here, "index.html"),
    },
  },
});
