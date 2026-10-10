# Environment and settings reference

Every setting the project reads, and where each one lives. A test (`backend/tests/test_env.py`)
fails if the backend starts reading a variable that is missing from this file or from
`.env.example`, so keep them in step.

## In production: where to change a setting

Production has three places. Change a setting in the right one, never directly on the running service:

| What | Where you change it | Takes effect |
|---|---|---|
| **Secrets** (the Gemini API key, the Twilio token) | **Google Cloud Secret Manager**: https://console.cloud.google.com/security/secret-manager?project=harvest-511117. Open the secret and add a new version. | After a redeploy. A running instance keeps the version it started with. |
| **Settings the pipeline passes** (`LIVE_MODEL`, `GEMINI_BACKEND`, `GOOGLE_CLOUD_LOCATION`, `MILL_NAME`, `PLANNER_NAME`, `DEMO_LANGUAGE`, `FIREBASE_WEB_CONFIG`, `GCP_PROJECT`, `GCP_REGION`) | **GitHub** repository variables: https://github.com/RaymonddC/Harvest/settings/variables/actions. `JWT_SECRET`, `WIF_PROVIDER` and `WIF_SERVICE_ACCOUNT` are GitHub *secrets* instead: https://github.com/RaymonddC/Harvest/settings/secrets/actions | On the next deploy: push to `main`, or run *Deploy* in the Actions tab. |
| **Everything else** (`TEXT_MODEL`, `VOICE_NAME`, `MAX_CALL_SECONDS`, the forecast numbers and so on) | The default in `backend/app/config.py`. There is no GitHub variable for these yet. To make one, follow "Adding a new setting" below. | After a merge to `main` redeploys it. |

The deploy copies the GitHub values into the Cloud Run service's environment variables. So **the
Cloud Run service shows what is running, but GitHub and Secret Manager are where you change it**.
`deploy.sh` replaces every Cloud Run variable on each run, so anything you set directly on the
service with `gcloud run services update` is wiped by the next deploy. Use that only for a quick
test, and set the GitHub variable too if you want to keep it.

To see what is live right now, without printing secrets:
```bash
gcloud run services describe harvest-gateway --region asia-southeast1 --format=yaml | grep -A1 "name: LIVE_MODEL"
```
No output means the service is using the default from the code.

## Adding a new setting

1. Read it in code: `backend/app/config.py` for the backend, `deploy/deploy.sh` for deploy-time
   settings, or `.github/workflows/deploy.yml` for GitHub secrets and variables.
2. Add it to the matching template: `.env.example` (backend) or `deploy/deploy.env.example` (deploy).
   Use an empty value, or a commented line if it has a default.
3. Add a row to the table below, with its default and whether it is a secret.
4. If it is a secret, store it in Secret Manager or GitHub secrets, never in a committed file.
5. If the cloud service needs it, pass it through `deploy/deploy.sh` and, for automatic deploys,
   through `.github/workflows/deploy.yml` plus a row in the GitHub table.

`backend/tests/test_env.py` fails when step 2 or 3 is missed for any of the three places.

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

| Variable | Default | Secret? | What it does | In production, change it in |
|---|---|---|---|---|
| `GOOGLE_API_KEY` | none | Yes | Gemini API key, read by the Google SDK. Only used with `GEMINI_BACKEND=api_key`; then it comes from the `gemini-api-key` secret. Leave it unset when using Vertex AI, or it overrides the Vertex sign-in. Not needed for anything but the voice call. | Secret Manager, secret `gemini-api-key`: add a new version, then redeploy |
| `LIVE_MODEL` | `gemini-2.5-flash-native-audio-preview-12-2025` | No | Gemini Live model for calls. Change it if Google retires the default. | GitHub variable `LIVE_MODEL`, then redeploy |
| `TEXT_MODEL` | `gemini-3.8-flash` | No | Gemini model for caption translation and the plain-language forecast note. Google retired `gemini-2.5-flash` for new users (it answers 404), so if this one is retired too, set the name the error message suggests. Both features fall back quietly when it fails. | Not settable from GitHub yet: the code default runs. See the rule above |
| `VOICE_NAME` | `Kore` | No | The agent's voice. | Not settable from GitHub yet: the code default runs. See the rule above |
| `VAD_SILENCE_MS` | `400` | No | How many milliseconds of silence end the farmer's turn, so the agent starts answering. Lower is faster but can cut off someone who pauses mid-sentence; raise it to 700 to 1000 if the agent interrupts. | Not settable from GitHub yet: the code default runs. See the rule above |
| `STORE_BACKEND` | `memory` | No | `memory` (local, in-process) or `firestore`. | Set by `deploy.sh` (`firestore`); not changeable from GitHub |
| `GOOGLE_CLOUD_PROJECT` | none | No | Project id, needed when `STORE_BACKEND=firestore`. | Set by `deploy.sh` from GitHub variable `GCP_PROJECT` |
| `SEED_ON_START` | true for `memory`, false for `firestore` | No | Reload the demo data on every start. | Set by `deploy.sh` (`false`); not changeable from GitHub |
| `MILL_NAME` | `Koperasi Sawit Maju` | No | The buying mill, spoken by the agent and shown in the header. | GitHub variable `MILL_NAME`, then redeploy |
| `PLANNER_NAME` | `Dewi` | No | The planner's name, shown in the header and on the Planner role. | GitHub variable `PLANNER_NAME`, then redeploy |
| `DEMO_LANGUAGE` | `Bahasa Indonesia` | No | Language the agent speaks. | GitHub variable `DEMO_LANGUAGE`, then redeploy |
| `DEMO_CROP` | `palm` | No | Default crop. | Not settable from GitHub yet: the code default runs. See the rule above |
| `CAPTION_TRANSLATE_TO` | `English` | No | Second caption line on the call screen. Empty turns it off. | Not settable from GitHub yet: the code default runs. See the rule above |
| `PLAN_START` | next Monday | No | First Monday of the forecast horizon (`YYYY-MM-DD`). | Not settable from GitHub yet: the code default runs. See the rule above |
| `FORECAST_WEEKS` | `5` | No | Weeks in the forecast. | Not settable from GitHub yet: the code default runs. See the rule above |
| `TARGET_KG_PER_WEEK` | `100000` | No | The mill's weekly target. | Not settable from GitHub yet: the code default runs. See the rule above |
| `GAP_TOLERANCE` | `0.2` | No | A week is a gap when supply is below target × (1 − this). | Not settable from GitHub yet: the code default runs. See the rule above |
| `MAX_CALL_ATTEMPTS` | `2` | No | A dropped call is retried until this many attempts. | Not settable from GitHub yet: the code default runs. See the rule above |
| `MAX_CALL_SECONDS` | `360` | No | Hard limit on one call. | Not settable from GitHub yet: the code default runs. See the rule above |
| `AUTH_REQUIRED` | `true` | No | Planner actions need the planner role. `false` leaves them open. | Not settable from GitHub yet: the code default runs. See the rule above |
| `JWT_SECRET` | a new random value each start | Yes | Signs sign-in tokens. Set a long random value (at least 32 characters) in the cloud. | GitHub secret `JWT_SECRET`, then redeploy (everyone signs in again) |
| `JWT_TTL_SECONDS` | `43200` (12 hours) | No | How long a sign-in lasts. | Not settable from GitHub yet: the code default runs. See the rule above |
| `HARVEST_NO_DOTENV` | unset | No | Set to `1` to ignore `.env` files entirely. The tests set it so a developer's own `.env` cannot change results. | Not used in production |
| `STATIC_DIR` | the repo's `web/` folder | No | Pages the backend serves. Left unset in the cloud, where Firebase Hosting serves them. | Left unset in production (Firebase Hosting serves the pages) |
| `CORS_ORIGINS` | `*` | No | Allowed browser origins, comma-separated. Set to your Hosting URL for anything real. | Not settable from GitHub yet: the code default runs. See the rule above |
| `FIREBASE_WEB_CONFIG` | none | No | Firebase web config JSON. Turns on live Firestore listeners in the dashboard. | GitHub variable `FIREBASE_WEB_CONFIG`, then redeploy |
| `TWILIO_ACCOUNT_SID` | none | No | Real phone channel. | Only when running `deploy.sh` by hand (`deploy/deploy.env`); the GitHub workflow does not pass it yet |
| `TWILIO_AUTH_TOKEN` | none | Yes | Real phone channel. In the cloud it comes from the `twilio-auth-token` secret. | Secret Manager, secret `twilio-auth-token`, created by hand |
| `TWILIO_FROM_NUMBER` | none | No | Real phone channel. | Only when running `deploy.sh` by hand (`deploy/deploy.env`); the GitHub workflow does not pass it yet |
| `PUBLIC_BASE_URL` | none | No | The service's own https URL. `deploy.sh` sets it when Twilio is configured. | Set by `deploy.sh` automatically |
| `REAL_CALLS_ENABLED` | `false` | No | Safety gate: real calls need this on **and** the number on the allow list. | Only when running `deploy.sh` by hand (`deploy/deploy.env`); the GitHub workflow does not pass it yet |
| `REAL_CALL_ALLOWLIST` | empty | No | Numbers a real call may dial. `*` allows any number. | Only when running `deploy.sh` by hand (`deploy/deploy.env`); the GitHub workflow does not pass it yet |

Using Vertex AI instead of an API key (the cloud default): set `GOOGLE_GENAI_USE_VERTEXAI=true`,
`GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` and a Vertex `LIVE_MODEL`, and leave `GOOGLE_API_KEY`
unset. The Google SDK reads these itself. Locally, sign in once with `gcloud auth application-default login`.
In the cloud the service signs in with its own account, which needs `roles/aiplatform.user`.

## Deploy settings (`deploy/deploy.env` or the shell)

| Variable | Default | What it does |
|---|---|---|
| `PROJECT` | none, required | Google Cloud project id. |
| `REGION` | `asia-southeast1` | Region for Cloud Run. |
| `GEMINI_BACKEND` | `vertex` | `vertex`: the service calls Vertex AI with its own Google account and stores no key. `api_key`: it uses the `gemini-api-key` secret. |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` | Vertex region for the Live API (with `vertex`). |
| `LIVE_MODEL` | `gemini-live-2.5-flash-native-audio` with `vertex`, unset with `api_key` | The Live model's name. It differs between Vertex and the Gemini API. |
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
| Variable | `GEMINI_BACKEND`, `GOOGLE_CLOUD_LOCATION`, `LIVE_MODEL` | Optional; see the deploy settings above. |

How to create the first three is in section 7 of `DEPLOY.md`.
