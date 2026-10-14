# Harvest-Call Agent: notes for a new session

Hackathon project (Google Cloud AI Builder Cup 2026, Manufacturing). Read `README.md` first, then `TODO.md`
(open work, items 10 to 12 are the voice and demo-resilience tasks), `DECISIONS.md` and `ENV.md`.

## Layout
- `backend/app/`: FastAPI gateway (`main.py`), Gemini Live relay (`live_session.py`), the agent's tools
  (`tools.py`), prompt (`prompt.py`), price rules (`rules_engine.py`), services, `access.py` and `auth.py`
  (users, roles, capabilities), stores (memory or Firestore).
- `frontend/`: the React dashboard (Vite), built into `frontend/dist` and served by Firebase Hosting. A teammate (Wilbert) owns it.
- `web/`: the call client (`call.html`, `js/call.js`, `js/audio-worklets.js`), `mic-test.html`, shared `js/data.js` and `samples/`;
  the build copies these into `dist` (list in `frontend/vite.config.js`: add any new file there). The other pages in `web/`
  (`index.html`, `setup.html`, ...) are the old vanilla dashboard and are no longer deployed; change the React app instead.
- `deploy/deploy.sh`, `.github/workflows/deploy.yml`: push to `main` deploys Cloud Run, Firestore rules and Hosting.

## Working rules
- Develop on the branch the session names, push it, and push to `main` only when the user has said to
  ("push it"). Pushing to `main` deploys to production. `main` also receives teammates' PRs: always
  `git fetch origin main`, merge it into your branch, test, push, then check `git merge-base --is-ancestor HEAD origin/main`.
  Never chain the push behind a silent `&&` guard (that once skipped four pushes without any message).
- Run tests: `cd backend && python -m pytest -q`. One known failure on Python 3.13:
  `test_audio_codec.py::test_decode_matches_stdlib_audioop_exactly` (`audioop` was removed).
- Local run: `cd backend && HARVEST_NO_DOTENV=1 python -m uvicorn app.main:app --port 8765` (in-memory store,
  seeded demo data, sign-in by picking a person). Do not use `pkill -f` or `pgrep -f` with a pattern that
  matches your own command line; use `fuser -k 8765/tcp`.
- Browser checks: Playwright with Chromium at `/opt/pw-browsers` (pass `executable_path`).
- Every new environment variable must be added to `.env.example`, `deploy/deploy.env.example` and `ENV.md`
  (`tests/test_env.py` checks it).
- Never ask for a key in chat: keys go in the environment settings (`GOOGLE_API_KEY`).

## State on 12 Oct 2026
- Done: deploy pipeline, demo sign-in with users, roles and capabilities (planner, coordinator; viewer and
  farmer are demo roles), Users page, farmer add/edit/delete/CSV with template, pagination, fixes for the
  confirm call, read-back and microphone, demo guide.
- Gemini now runs on Vertex AI (project harvest-511117, us-central1; the AI Studio key is out of credits). Locally,
  `VERTEX_ACCESS_TOKEN` (short-lived, about 1 hour) is used by `live_session.genai_client()`; Cloud Run uses its own service account.
- TODO item 12 is done: real call recorded with a scripted farmer, `web/samples/gap-fill.json` rebuilt with sound
  (`web/samples/clips/`), the replay plays the clips, and the call page has "Play the farmer for me". Rebuild with
  `backend/scripts/sample_call.py` (clips, record, build). Reply delay measured: about 1.3 to 2.4 s with the 400 ms VAD wait.
- Multi-crop campaigns (backend) are built (TODO item 13); the dashboard's five campaign lookups still need the picked crop.
- Open: prompt problems found in the recordings (TODO item 12), and check the new voice path on the deployed site.
