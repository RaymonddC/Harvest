# Harvest-Call Agent

An AI voice agent that phones smallholder farmers for a mill, builds a live weekly supply
forecast from their answers, and negotiates gap-filling deals inside the mill's price limits.
Every deal waits for a human planner's approval, and the agent then confirms it by voice.

Google Cloud AI Builder Cup 2026 · Manufacturing. All data is synthetic.

```
Browser call client ──WebSocket──▶ Voice gateway (Cloud Run, FastAPI) ──▶ Gemini Live API
      (farmer)                        │  call manager · tool handlers
                                      │  rules engine (floor / ceiling / offer ladder)
                                      ▼
                                  Firestore ◀── forecast job (Cloud Run job)
                                      │
Planner dashboard (Firebase Hosting) ◀┘  live listeners; actions go through the gateway API
```

## Run it locally (no GCP needed)

```bash
cd backend
pip install -r requirements-dev.txt
export GOOGLE_API_KEY=...          # Gemini API key from AI Studio (PowerShell: $env:GOOGLE_API_KEY="...")
python -m uvicorn app.main:app --port 8000
```

- Planner pages: http://localhost:8000/setup.html, http://localhost:8000 (live forecast), http://localhost:8000/approvals.html
- Call client: http://localhost:8000/call.html (use headphones)

Local mode uses an in-memory store, seeded on start with a synthetic palm cooperative
(Koperasi Sawit Maju, planner Dewi, Bahasa Indonesia, prices in IDR). The forecast matches the
wireframe: 92, 85, 61, 98 and 90 t against a 100 t target, so week 3 has a 39 t gap. Six week-3
answers are unsure and count for half. The pages update over server-sent events. Without an
API key, everything works except the voice session itself.

### Demo walk-through (matches the design canvas and the 3-minute video plan)

1. **Setup:** check the farmer list and the price limits (floor Rp 2,900, reference 3,100,
   ceiling 3,350), then **Start campaign**.
2. **Live forecast:** shows the week 3 gap, why it is short, and a shortlist of 15 farmers
   (22.8 t) plus a rival quote (12 t).
3. **Call client:** answer *Pak Rahmat* and play the farmer. The agent says it is an AI, asks
   for consent, then for the harvest. It reads the answer back from the Captured card and saves
   it. Captions show Bahasa Indonesia with an English line underneath.
4. **Start gap-fill calls:** answer as a shortlisted farmer and counter the offer. The
   check_offer card shows the counter against the floor, reference and ceiling, and the
   pending volume appears hatched on week 3.
5. **Approvals:** approve the offers and the gap meter fills. Undo works until the farmer has
   heard the confirmation. Answer the confirmation call to see "Deal confirmed".

## Tests

```bash
cd backend && python -m pytest -q
```

The suite covers the rules engine, including a randomised check that no price ever leaves the
limits. It also covers the forecast and seed data, the six tools, the HTTP API, and the voice
gateway: a scripted gap-fill call runs through a fake Live session, and a dropped call is
retried once.

## Deploy

```bash
gcloud secrets create gemini-api-key --data-file=- <<< "$GOOGLE_API_KEY"
cp .firebaserc.example .firebaserc   # set your project id
PROJECT=my-project REGION=asia-southeast1 \
FIREBASE_WEB_CONFIG='{"apiKey":"...","projectId":"my-project",...}' \
PLANNER_TOKEN=choose-one \
deploy/deploy.sh
```

This deploys the gateway to Cloud Run, the forecast job as a Cloud Run job, the Firestore
rules and the dashboard to Firebase Hosting, and then seeds the demo data. The Cloud Run
service account needs Firestore access (`roles/datastore.user`). The browser opens
WebSockets to the Cloud Run URL directly, because Hosting rewrites do not carry WebSockets.

## Layout

| Path | What it is |
|---|---|
| `backend/app/main.py` | FastAPI app: planner API, SSE stream, `/ws/call/{id}`, static files in local mode |
| `backend/app/live_session.py` | Voice gateway: browser audio ⇄ Gemini Live, tool calls, captions, transcript |
| `backend/app/tools.py` | The six tools and their per-call handlers |
| `backend/app/rules_engine.py` | Floor, ceiling and offer ladder; `check_offer` decisions |
| `backend/app/forecast.py` | Weekly totals, gap flags and the pull-forward shortlist |
| `backend/app/services.py` | Shared operations: offers, approvals, campaigns, retries |
| `backend/app/prompt.py` | System instruction: persona, six-stage script, calendar (no prices) |
| `backend/app/store.py` | `MemoryStore` (local and tests) and `FirestoreStore` |
| `backend/app/seed_data.py` | Synthetic farmers, harvests, limits and the rival quote |
| `backend/app/forecast_job.py` | Cloud Run job entry point |
| `web/setup.html`, `web/index.html`, `web/approvals.html` (+ `web/js/*.js`) | Planner pages: setup, live forecast, approvals |
| `web/call.html`, `web/js/call.js`, `web/js/audio-worklets.js` | Browser call client: 16 kHz mic capture, 24 kHz playback, barge-in |

## Guardrails, and where they live in code

| Guardrail | Enforcement |
|---|---|
| AI disclosure in the first sentence (VA-2) | Exact opening line in `prompt.py`; badge always on the call screen |
| Prices only from `check_offer` (VA-5) | `save_offer` rejects any price `check_offer` did not return on this call (`tools.py`) |
| Read-back before saving (VA-3) | `record_harvest` runs twice: unconfirmed (returns the read-back sentence), then confirmed |
| Floor and ceiling (G3) | `rules_engine.check_offer`; re-checked in `create_offer` and again on approval |
| Out-of-limit requests go to the planner | `escalate` decision → offer saved as `escalated`; Approve stays disabled until the limits allow it |
| Agent never sees the limits | Prompt and `get_reference_price` expose only the reference price |
| Reference price read aloud first | Prompt stage 4; `get_reference_price` returns the sentence to say |
| Consent before a transcript is saved | `end_call(transcript_consent)`; the transcript is dropped when false |
| Human approval on every deal | Offers start `pending`; only approved offers count in the forecast |
| One farmer per call | Tool handlers are bound to the call's farmer and cannot read others |
| Retry once; dropped calls keep saved data (NFR) | `services.finish_call` |

## Configuration

See `.env.example`. The main settings are `GOOGLE_API_KEY` (or Vertex AI variables),
`STORE_BACKEND`, `LIVE_MODEL`, `DEMO_LANGUAGE`, `MILL_NAME`, `PLAN_START`,
`TARGET_KG_PER_WEEK`, `GAP_TOLERANCE` and `PLANNER_TOKEN`.

The Live model name changes often. If the default is retired, set `LIVE_MODEL` to the
current native-audio model listed in the Gemini API docs.
