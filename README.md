# Harvest-Call Agent

A Gemini Live voice agent that phones smallholder suppliers across rural Southeast Asia, forecasts the mill's
weekly supply from their answers, and negotiates the gaps inside the mill's price limits. Every deal waits for a
human planner, and the agent confirms it by voice once approved.

**Google Cloud AI Builder Cup 2026 · Manufacturing: Intelligent Operations & Industrial Efficiency**

- Live product: [harvest-511117.web.app](https://harvest-511117.web.app) (sign in with the demo planner account shown on the sign-in page)
- Demo video (3 min): [youtu.be/LCkVVnJKFNM](https://youtu.be/LCkVVnJKFNM)
- Team: Gary Marvelim (lead), Raymond Chrisandy Runtuwene, Wilbert

Every figure in the prototype runs on synthetic data.

## The problem

In rural Southeast Asia, a mill's suppliers cannot be reached by software at all. About 100 million smallholders
farm the region, two hectares each at most, and in Indonesia they hold 40% of the oil palm area, heading for 60%
this decade (WWF / Climate Focus 2021; BPS 2021 via WRI Indonesia). They have a basic handset, often no mobile data,
and no single language across a mill's catchment, so an app or a portal reaches nobody. Satellites and yield
models estimate a whole region but never ask the grower. The shortfall shows up at the weighbridge, when the only
fix left is a rush price.

The one channel that reaches every farmer is the phone already in their pocket. Harvest-Call uses it: an AI agent
places the call itself, in the farmer's language, every week, and ends it with a structured answer or a deal.

## One week, three people

| | 1 · Ask | 2 · Forecast | 3 · Negotiate | 4 · Confirm |
|---|---|---|---|---|
| **Farmer** (basic phone, no data) | Answers an ordinary call and says how much he will have, and when | Nothing to install, nothing to fill in | A second call asks if he can bring some of a later harvest into the short week | Hears the approved deal read back and which mill to bring it to |
| **The agent** (Gemini Live on Vertex AI) | Says it is an AI, asks consent, reads every number back before saving | Files the answer into its week and flags the week that falls short | Asks `check_offer` for the one price it may say; it never sees the range | Calls back only after approval |
| **The planner** (dashboard) | Loads the farmers, sets floor, reference and ceiling | Sees week 3 is 39 t short and the 15 farmers who could cover 22.8 t | Watches offers arrive in the approval queue | Approves or rejects; nothing is final until she does |

## Features

The dashboard is one workspace in four steps.

**1 · Prepare**
- Farmer database with CSV import, a satellite plot map, and each plot matched to its nearest mill by road
  (Google Routes API: road distance, truck time, the route drawn on a click; plots over 2 h are flagged because
  fresh fruit loses quality while it waits)
- Campaigns per crop: weeks, target, price range (floor, market, ceiling), farmer segments
- An agent persona per campaign: voice, style, languages and the planner's own questions

**2 · Call**
- One click starts a round: the agent dials every farmer in the campaign who needs a call and has Agent calls on
- Gemini Live in eight languages (Bahasa Indonesia, Bahasa Malaysia, English, Javanese, Sundanese, Thai, Vietnamese,
  Filipino), with barge-in, live captions and a read-back before anything is saved
- The Calls page follows every call live: the conversation, what was saved, what was offered
- Transcript and recording kept only with the farmer's yes; planner-only playback; delete on request

**3 · Decide**
- Approval queue: each offer beside the rival quote for that week and its effect on the gap
- Approve, reject or undo; the agent calls the farmer back only after approval
- Purchase order and goods receipt as PDFs; deliveries and payments (mark paid, unpaid total)

**4 · Track**
- Live supply forecast; unsure answers count for half
- A BigQuery ML (ARIMA_PLUS) forecast from past deliveries beside what farmers said; supply data exported to
  BigQuery for Looker Studio (no names or phone numbers)
- Gemini's call summary and mood after each consented call; an unhappy call becomes a churn signal
- A daily brief: once a day Gemini sums up the last 24 hours and keeps the planner's task list up to date
- Farmer relationship: reliability, segments, notes, complaints and follow-ups; a calendar of calls, harvests and deliveries

## Architecture

One Google Cloud project, deployed in `asia-southeast1`.

```
 Farmer (basic phone) ──Twilio──┐                      ┌──▶ Vertex AI: Gemini Live (speech both ways, tool calls)
                                ▼                      │        and a Gemini text model (summaries, captions, brief)
 Planner (browser) ─▶ Firebase Hosting ─▶ Cloud Run: harvest-gateway (FastAPI)
                       React dashboard     relays the call audio, runs the 8 agent tools
                       + call client       and the rules engine, serves the planner API
                                                       │
            ┌──────────────┬───────────────┬───────────┴──┬────────────────┬──────────────────┐
         Firestore      BigQuery +      Cloud Storage    Secret Manager    Maps JavaScript +
         farmers, calls, BigQuery ML    call recordings  telephony key     Routes API
         offers, live    (ARIMA_PLUS)   (90-day rule)                      (plot map, road time)
         forecast
            ▲
 Cloud Scheduler, hourly: rolls the weeks, starts scheduled campaigns, refreshes BigQuery, fetches road routes,
 writes the daily brief.      GitHub Actions → Cloud Build on every push to main (Workload Identity Federation).
```

| Layer | Services | Why |
|---|---|---|
| Experience | Firebase Hosting, React dashboard, vanilla JS call client | Nothing for the farmer to install |
| Intelligence | Vertex AI: Gemini 2.5 Flash native audio for the call; a Gemini text model for summaries, captions and the brief | Speech in, speech out, with no pipeline to stitch |
| Compute | Cloud Run `harvest-gateway`, Cloud Scheduler (hourly) | Scales to zero between campaigns |
| Data | Firestore, BigQuery + BigQuery ML, Cloud Storage, Secret Manager | Every promise is a record, not a memory |
| Ground truth | Maps JavaScript API, Routes API, Twilio Programmable Voice | Road time, and a real number that rings |

Both model names are settings (`LIVE_MODEL`, `TEXT_MODEL`) because preview names are retired often. `TEXT_MODEL`
defaults to `gemini-3.8-flash`; where that name is not available the service falls back to `gemini-2.5-flash`
(`backend/app/gemini_text.py`), which is what writes the text on the deployed service today.

## Guardrails, and where they live in code

| Guardrail | Enforcement |
|---|---|
| The model never sees the price range | The prompt and `get_reference_price` carry only the reference price. `check_offer` returns just the next price the agent may say (`rules_engine.py`) |
| Prices only from `check_offer` | `save_offer` rejects any price `check_offer` did not return on this call (`tools.py`) |
| Floor and ceiling | `rules_engine.check_offer`; re-checked in `create_offer` and again on approval. Out-of-range requests are saved as `escalated` ("Needs planner") |
| Human approval on every deal | Offers start `pending`; only approved offers count in the forecast; the confirmation call happens only after approval |
| Read-back before saving | `record_harvest` runs twice: unconfirmed (returns the read-back sentence), then confirmed |
| AI disclosure first | The opening line is fixed in `prompt.py`; an AI badge is always on the call screen |
| One farmer per call | Tool handlers are bound to the call's farmer and cannot read others |
| Real calls only to approved numbers | Phone rounds go only to farmers with Agent calls on, behind `REAL_CALLS_ENABLED` and `REAL_CALL_ALLOWLIST` |
| Retry once; dropped calls keep saved data | `services.finish_call` |

## Personal data (Indonesia's PDP Law, Law 27/2022)

Our reading, not legal advice; the details are in `DECISIONS.md` ("Call audio recording").

- The agent asks consent in the call's language and says the purpose, what is kept (the transcript, and the
  recording when recording is on) and for how many days (`prompt.NOTICES`).
- Nothing is kept without a yes: no transcript, no recording, no Gemini summary. The stored yes is the proof.
- One retention setting, `CALL_AUDIO_RETENTION_DAYS` (90), drives the notice, the stored expiry, the playback
  refusal and the bucket's lifecycle rule (`deploy/setup-call-audio.sh`).
- Only planners can play a recording, and a planner can delete one on request.
- The BigQuery export carries no names and no phone numbers.

## Cost and performance

For one cooperative of 301 farmers called every week (about 1,384 calls a month), at published rates read on
18 Oct 2026: a 2-minute call costs about **$0.24** (Twilio $0.21, Gemini Live audio $0.028, Cloud Run $0.003), so
about **$1.19 per farmer a month** and **$358 for the month**. Call length is the whole cost model: at the
campaign's 6-minute cap the month is about $1,040. Telephony is 87% of it. Firestore, Cloud Storage and BigQuery
sit at or near the free tier at this volume. Treat these as an order of magnitude, not a quote.

Reply delay measured on a real call: **1.3 to 2.4 s**, including a 400 ms wait for the farmer to stop speaking.
That is above the comfortable band for voice agents (0.5 to 1 s); shortening the endpointing wait and moving off a
preview model are the first optimisations.

## Run it locally (no Google Cloud needed)

From the repo root:

```bash
npm start          # backend (port 8000) + React dashboard (http://localhost:5173), in-memory demo data
npm run start:env  # the same, reading backend/.env too (Gemini credentials)
npm run start:phone  # real phone calls from your PC: Twilio settings from .env, a Cloudflare quick tunnel, a Vertex token from gcloud
npm test           # the backend tests
```

Sign in by picking a person (the planner is Dewi, `dewi` / `harvest-demo`). The in-memory store is seeded with a
synthetic palm cooperative, Koperasi Sawit Maju: 301 farmers in the main campaign around two mills near
Pekanbaru, week totals of 92, 85, 61, 98 t against a 100 t target (week 3 is 39 t short), recent consented calls
with Gemini summaries, paid and unpaid deliveries, and a rival quote. Without Gemini credentials everything works
except the voice session and the Gemini text features.

To run the backend on its own:

```bash
cd backend
pip install -r requirements-dev.txt
export GOOGLE_API_KEY=...   # or the Vertex AI variables in ENV.md
HARVEST_NO_DOTENV=1 python -m uvicorn app.main:app --port 8000
```

If nobody can play the farmer, the call page has **Play the farmer for me** and **Watch a sample call** (a
recorded gap-fill call, labelled as a sample, that saves nothing).

### Demo walk-through

1. **Overview:** where every farmer stands, what we have against what we lack, and the daily brief.
2. **Farmers:** the plot map with the mills; colour by truck time; click a plot to see its road to the mill.
3. **Campaign → Start calling:** the agent phones the farmers; the Calls page follows each call live.
4. **The call:** AI disclosure and consent, the harvest question, the read-back.
5. **Forecast:** the week 3 gap, the shortlist, and the BigQuery ML forecast; start gap-fill calls and counter the offer.
6. **Approvals:** approve; the confirmation call names the farmer's nearest mill; record the delivery, mark it
   paid, download the receipt and the purchase order.

## Tests

```bash
cd backend && python -m pytest -q
```

324 automated tests (297 test functions, some parametrised): the planner API and sign-in, price rules and
approvals (including a randomised check that no price ever leaves the limits), campaigns and scheduling, consent
and records, the forecast, mills and track record, the agent's tools and prompt, and voice, audio and telephony (a
scripted gap-fill call runs through a fake Live session). On Python 3.13 one test is skipped: it compares our G.711
decoder against Python's `audioop`, which 3.13 removed; it runs in CI on 3.12.

## Deploy

A push to `main` deploys through GitHub Actions: the gateway to Cloud Run, the Firestore rules, and the dashboard
to Firebase Hosting, and creates the hourly Cloud Scheduler job. Step by step: [DEPLOY-STEPS.md](DEPLOY-STEPS.md);
the full guide, including automatic deploys: [DEPLOY.md](DEPLOY.md). The short manual version:

```bash
gcloud secrets create gemini-api-key --data-file=- <<< "$GOOGLE_API_KEY"   # or use Vertex AI with the service account
cp .firebaserc.example .firebaserc   # set your project id
PROJECT=my-project REGION=asia-southeast1 \
FIREBASE_WEB_CONFIG='{"apiKey":"...","projectId":"my-project",...}' \
deploy/deploy.sh
```

The browser opens WebSockets to the Cloud Run URL directly, because Hosting rewrites do not carry WebSockets.

## Configuration

Copy `.env.example` to `.env`; every setting, and where it lives (local, cloud, GitHub), is in [ENV.md](ENV.md).
The main ones: Gemini (`GOOGLE_API_KEY` or the Vertex AI variables, `LIVE_MODEL`, `TEXT_MODEL`), the store
(`STORE_BACKEND`), the plan (`PLAN_START`, `TARGET_KG_PER_WEEK`, `GAP_TOLERANCE`), sign-in (`AUTH_REQUIRED`,
`JWT_SECRET`), the phone line (`TWILIO_*`, `PUBLIC_BASE_URL`, `REAL_CALLS_ENABLED`, `REAL_CALL_ALLOWLIST`),
recordings (`CALL_AUDIO_BUCKET`, `CALL_AUDIO_RETENTION_DAYS`), BigQuery (`BIGQUERY_DATASET`), maps and routes
(`MAPS_API_KEY`, `MILL_ROUTES`) and the daily brief (`DAILY_BRIEF`).

## Layout

| Path | What it is |
|---|---|
| `backend/app/main.py` | FastAPI app: planner API, live data stream, `/ws/call/{id}` |
| `backend/app/live_session.py` | Voice gateway: call audio ⇄ Gemini Live, tool calls, captions, transcript, recording |
| `backend/app/tools.py` | The agent's eight tools and their per-call handlers |
| `backend/app/rules_engine.py` | Floor, ceiling and offer ladder; `check_offer` decisions |
| `backend/app/prompt.py` | System instruction: persona, consent notice, call stages, calendar (no prices) |
| `backend/app/forecast.py`, `services.py` | Weekly totals, gap flags, the pull-forward shortlist; offers, approvals, campaigns, retries |
| `backend/app/mills.py` | Mills, nearest mill by road (Routes API), truck time, catchment |
| `backend/app/call_insights.py`, `daily_brief.py`, `gemini_text.py` | Gemini summaries and mood, the daily brief and task list, the text-model helper |
| `backend/app/bq_export.py` | BigQuery export and the BigQuery ML forecast |
| `backend/app/crm.py`, `track_record.py`, `purchase_order.py` | Segments and churn signals; promises and deliveries; PDFs |
| `backend/app/twilio_channel.py`, `audio_codec.py` | The real phone channel and its mu-law codec |
| `backend/app/store.py`, `seed_data.py` | `MemoryStore` and `FirestoreStore`; the synthetic demo data |
| `frontend/` (React, Vite) | The planner dashboard, built into `frontend/dist` and served by Firebase Hosting |
| `web/call.html`, `web/js/call.js`, `web/js/audio-worklets.js` | Browser call client: 16 kHz mic capture, 24 kHz playback, barge-in |

## What comes next (not built)

- **Next:** farmers call in, not just out; Document AI reads the weighbridge ticket from a photo; Gemini vision
  grades the fruit from a photo of the load.
- **Later:** BigQuery ML plans the quarter's crushing schedule; EUDR proof for every plot (from 30 Dec 2026 the EU
  needs a geolocation and a no-deforestation check per plot) with Earth Engine and BigQuery; rank every plot by kg
  per hectare so field support goes where it pays.
