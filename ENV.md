# Environment and settings reference

Every setting the project reads, and where each one lives. A test (`backend/tests/test_env.py`)
fails if the backend starts reading a variable that is missing from this file or from
`.env.example`, so keep them in step.

## Where settings live

| Where | File or place | Committed? | Used by |
|---|---|---|---|
| Your machine, running the backend | `.env` (copy of `.env.example`) | No, git-ignored | The backend, read at start. Variables already set in your shell win; blank values are ignored. |
| Your machine, deploying | `deploy/deploy.env` (copy of `deploy/deploy.env.example`) | No, git-ignored | `deploy/deploy.sh`. Variables already exported in your shell win. |
| The running service | Cloud Run environment variables | n/a | Set by `deploy.sh` from the deploy settings below. |
| Secrets in the cloud | Secret Manager: `gemini-api-key`, `twilio-auth-token` | n/a | Mounted into the service by `deploy.sh`. |
| Automatic deploys | GitHub repository secrets and variables | n/a | `.github/workflows/deploy.yml` |

Never commit a real `.env`, `deploy/deploy.env`, key or token.

## Backend settings (`.env` locally, Cloud Run variables in the cloud)

| Variable | Default | Secret? | What it does |
|---|---|---|---|
| `GOOGLE_API_KEY` | none | Yes | Gemini API key, read by the Google SDK. In the cloud it comes from the `gemini-api-key` secret. Not needed for anything but the voice call. |
| `LIVE_MODEL` | `gemini-2.5-flash-native-audio-preview-09-2025` | No | Gemini Live model for calls. Change it if Google retires the default. |
| `TEXT_MODEL` | `gemini-2.5-flash` | No | Gemini model for caption translation and the plain-language forecast note. |
| `VOICE_NAME` | `Kore` | No | The agent's voice. |
| `STORE_BACKEND` | `memory` | No | `memory` (local, in-process) or `firestore`. |
| `GOOGLE_CLOUD_PROJECT` | none | No | Project id, needed when `STORE_BACKEND=firestore`. |
| `SEED_ON_START` | true for `memory`, false for `firestore` | No | Reload the demo data on every start. |
| `MILL_NAME` | `Koperasi Sawit Maju` | No | The buying mill, spoken by the agent and shown in the header. |
| `PLANNER_NAME` | `Dewi` | No | The planner's name, shown in the header and on the Planner role. |
| `DEMO_LANGUAGE` | `Bahasa Indonesia` | No | Language the agent speaks. |
| `DEMO_CROP` | `palm` | No | Default crop. |
| `CAPTION_TRANSLATE_TO` | `English` | No | Second caption line on the call screen. Empty turns it off. |
| `PLAN_START` | next Monday | No | First Monday of the forecast horizon (`YYYY-MM-DD`). |
| `FORECAST_WEEKS` | `5` | No | Weeks in the forecast. |
| `TARGET_KG_PER_WEEK` | `100000` | No | The mill's weekly target. |
| `GAP_TOLERANCE` | `0.2` | No | A week is a gap when supply is below target × (1 − this). |
| `MAX_CALL_ATTEMPTS` | `2` | No | A dropped call is retried until this many attempts. |
| `MAX_CALL_SECONDS` | `360` | No | Hard limit on one call. |
| `AUTH_REQUIRED` | `true` | No | Planner actions need the planner role. `false` leaves them open. |
| `JWT_SECRET` | a new random value each start | Yes | Signs sign-in tokens. Set a long random value (at least 32 characters) in the cloud. |
| `JWT_TTL_SECONDS` | `43200` (12 hours) | No | How long a sign-in lasts. |
| `HARVEST_NO_DOTENV` | unset | No | Set to `1` to ignore `.env` files entirely. The tests set it so a developer's own `.env` cannot change results. |
| `STATIC_DIR` | the repo's `web/` folder | No | Pages the backend serves. Left unset in the cloud, where Firebase Hosting serves them. |
| `CORS_ORIGINS` | `*` | No | Allowed browser origins, comma-separated. Set to your Hosting URL for anything real. |
| `FIREBASE_WEB_CONFIG` | none | No | Firebase web config JSON. Turns on live Firestore listeners in the dashboard. |
| `TWILIO_ACCOUNT_SID` | none | No | Real phone channel. |
| `TWILIO_AUTH_TOKEN` | none | Yes | Real phone channel. In the cloud it comes from the `twilio-auth-token` secret. |
| `TWILIO_FROM_NUMBER` | none | No | Real phone channel. |
| `PUBLIC_BASE_URL` | none | No | The service's own https URL. `deploy.sh` sets it when Twilio is configured. |
| `REAL_CALLS_ENABLED` | `false` | No | Safety gate: real calls need this on **and** the number on the allow list. |
| `REAL_CALL_ALLOWLIST` | empty | No | Numbers a real call may dial. `*` allows any number. |

Using Vertex AI instead of an API key: set `GOOGLE_GENAI_USE_VERTEXAI=true`,
`GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION`. The Google SDK reads these itself.

## Deploy settings (`deploy/deploy.env` or the shell)

| Variable | Default | What it does |
|---|---|---|
| `PROJECT` | none, required | Google Cloud project id. |
| `REGION` | `asia-southeast1` | Region for Cloud Run. |
| `SERVICE` / `JOB` | `harvest-gateway` / `harvest-forecast` | Cloud Run service and job names. |
| `MILL_NAME`, `PLANNER_NAME`, `DEMO_LANGUAGE` | as above | Passed to the service. |
| `FIREBASE_WEB_CONFIG` | none | Passed to the service and written into `web/config.js`. |
| `JWT_SECRET` | a new random value each deploy | Passed to the service. Fix it to keep people signed in across deploys. |
| `SEED_DEMO_DATA` | `true` | Replace everything in Firestore with the demo data after deploying. Use `true` on the first deploy only. |
| `SKIP_API_ENABLE` | `false` | Skip enabling Google Cloud APIs. Automatic deploys set `true`. |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | none | If all three are set, `deploy.sh` wires up the phone channel. The token's value is only checked here; the secret itself must exist in Secret Manager as `twilio-auth-token`. |
| `REAL_CALLS_ENABLED`, `REAL_CALL_ALLOWLIST` | `false`, empty | The real-call gate, passed to the service. |

## Automatic deploys (GitHub repository settings)

| Type | Name | Value |
|---|---|---|
| Secret | `WIF_PROVIDER` | The Workload Identity provider path. |
| Secret | `WIF_SERVICE_ACCOUNT` | The deployer account's email. |
| Secret | `JWT_SECRET` | Optional; keeps people signed in across deploys. |
| Variable | `GCP_PROJECT` | Project id (required). |
| Variable | `GCP_REGION` | Region, defaults to `asia-southeast1`. |
| Variable | `MILL_NAME`, `PLANNER_NAME`, `DEMO_LANGUAGE`, `FIREBASE_WEB_CONFIG` | Optional. |

How to create the first three is in section 7 of `DEPLOY.md`.
