# Deploying Harvest to Google Cloud

For a short, ordered walkthrough that starts from nothing, use [DEPLOY-STEPS.md](DEPLOY-STEPS.md).
This guide is the reference behind it.

This guide covers three things: running it locally (what a friend needs), deploying it to
Google Cloud by hand, and deploying it automatically on every push to `main`.

> **Status:** `deploy/deploy.sh` and `.github/workflows/deploy.yml` have not been run end to end
> by the author of this guide. Expect to fix small permission errors on the first run. The
> "Troubleshooting" section lists the likely ones.

## 1. What gets deployed

| Piece | Runs on | Deployed by |
|---|---|---|
| Voice gateway and planner API (`backend/`, FastAPI) | Cloud Run service `harvest-gateway` | `gcloud run deploy --source backend` |
| Forecast job (`python -m app.forecast_job`) | Cloud Run job `harvest-forecast` | `gcloud run jobs deploy` |
| Dashboard (`frontend/`, React, built into `frontend/dist`) and call client (`web/`, copied into the build) | Firebase Hosting, at `https://PROJECT.web.app` | `deploy/deploy.sh` (builds, then `firebase deploy --only hosting`) |
| Data | Firestore (Native mode) | created once; rules deployed with Hosting |
| Gemini access | Vertex AI, called with the service's own Google account (`roles/aiplatform.user`). No key is stored. With `GEMINI_BACKEND=api_key` instead: Secret Manager secret `gemini-api-key`. | permission granted once |

The browser opens its WebSocket straight to the Cloud Run URL, because Firebase Hosting
rewrites do not carry WebSockets.

## 2. Who needs what

| | Needs a Google Cloud project and billing? | Needs a Gemini API key? | Needs `gcloud` / `firebase` CLI? |
|---|---|---|---|
| **A friend running locally** | No | Yes, their own (free, from Google AI Studio). Without one, everything works except the voice call. | No |
| **You, deploying by hand** | Yes | Yes | Yes |
| **GitHub Actions deploying** | Yes (the same project) | Stored in Secret Manager, not in GitHub | Installed by the workflow |

## 3. Running locally (for you or a friend)

Nothing here touches Google Cloud. Local mode keeps data in memory and re-seeds it on every
start, so each person has their own private copy and nothing is shared.

```bash
git clone https://github.com/RaymonddC/Harvest.git
cd Harvest/backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
export GOOGLE_API_KEY=your-key-from-aistudio.google.com   # PowerShell: $env:GOOGLE_API_KEY="..."
python -m uvicorn app.main:app --port 8000
```

Then open http://localhost:8000/setup.html (planner pages) and http://localhost:8000/call.html
(call client, use headphones).

Things to know:

- **Python version:** use 3.12, which is what the Dockerfile and CI use. On 3.13 one test
  (`test_decode_matches_stdlib_audioop_exactly`) fails because `audioop` was removed.
- **Settings can live in a `.env` file.** Run `cp .env.example .env` and put your key in it; the
  backend reads it at start (from the repo root or `backend/`), so you can skip the `export`. A
  variable already set in your shell wins. `.env` is git-ignored. Every setting is listed in
  [ENV.md](ENV.md).
- **Each person uses their own API key.** Do not share yours; a shared key shares its quota.
- **After the first clone, the daily routine is just:** activate the venv, export the key,
  start uvicorn. Run `git pull` and `pip install -r requirements-dev.txt` when dependencies change.
- **Tests:** `cd backend && python -m pytest -q`.

## 4. One-time Google Cloud setup

Do this once per project. Replace the values at the top. Run it in
[Google Cloud Shell](https://console.cloud.google.com) (the `>_` icon in the console, where `gcloud`
is preinstalled and signed in), or install the gcloud CLI and `firebase-tools` on your own machine
first (see step 6).

```bash
export PROJECT=my-project-id
export REGION=asia-southeast1

gcloud auth login
gcloud config set project $PROJECT
```

1. **Create the project and link billing** in the console (https://console.cloud.google.com).
   Cloud Run needs a billing account. Note the project id.

2. **Create the Firestore database** (Native mode):
   ```bash
   gcloud services enable firestore.googleapis.com
   gcloud firestore databases create --location=$REGION --type=firestore-native
   ```

3. **Add Firebase to the project.** In https://console.firebase.google.com choose
   *Add project* and pick the existing Google Cloud project, or run
   `gcloud services enable firebase.googleapis.com cloudresourcemanager.googleapis.com`, wait a
   minute, then `npx firebase-tools projects:addfirebase $PROJECT`. Hosting needs this. Without the
   API enabled the command fails with `403 Firebase Management API has not been used`.

4. **Gemini access.** The default is Vertex AI: nothing to store, you only grant a permission in
   step 5. Enable its API with `gcloud services enable aiplatform.googleapis.com`.

   *Option: use a Gemini API key instead.* Google's newer "AQ." AI Studio keys are reported to fail
   with the Gemini API, so use this only with a key you have tested. Run
   `gcloud services enable secretmanager.googleapis.com`, then
   `printf '%s' "$GOOGLE_API_KEY" | gcloud secrets create gemini-api-key --data-file=-`, give the runtime
   account `roles/secretmanager.secretAccessor` on the secret, and deploy with `GEMINI_BACKEND=api_key`.

5. **Let the Cloud Run runtime use Firestore and Vertex AI.** By default Cloud Run runs as
   the Compute Engine default service account:
   ```bash
   PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
   RUNTIME_SA=$PROJECT_NUMBER-compute@developer.gserviceaccount.com
   gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$RUNTIME_SA \
     --role=roles/datastore.user --condition=None
   gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$RUNTIME_SA \
     --role=roles/aiplatform.user --condition=None
   # the source build also runs as this account
   for role in roles/cloudbuild.builds.builder roles/storage.objectViewer \
               roles/artifactregistry.writer roles/logging.logWriter; do
     gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$RUNTIME_SA \
       --role=$role --condition=None --quiet >/dev/null
   done
   ```

6. **Install the CLIs** on the machine you deploy from: the
   [gcloud CLI](https://cloud.google.com/sdk/docs/install) and
   `npm install -g firebase-tools`, then `firebase login`.

7. **(Optional) Get the Firebase web config** so the dashboard uses live Firestore listeners.
   Without it the dashboard falls back to server-sent events from the gateway, which also works.
   ```bash
   npx firebase-tools apps:create web harvest --project $PROJECT
   npx firebase-tools apps:sdkconfig web --project $PROJECT   # copy the JSON object it prints
   ```

8. **Point the Firebase CLI at your project:** `cp .firebaserc.example .firebaserc` and put the
   project id in it. (`.firebaserc` is git-ignored; `deploy.sh` also passes `--project`.)

## 5. First deploy (by hand)

```bash
cd Harvest
PROJECT=$PROJECT REGION=$REGION \
FIREBASE_WEB_CONFIG='{"apiKey":"...","authDomain":"...","projectId":"..."}' \
bash deploy/deploy.sh
```

`FIREBASE_WEB_CONFIG` is optional. There is no password: the site opens on a page where you pick
a person (Dewi the planner, Budi the coordinator, a guest viewer or a farmer), and what they may do depends on their role; the planner manages people on the Users page. `JWT_SECRET` is optional too; the script makes one if you
don't pass it.

The script, in order: enables the APIs, deploys the gateway, deploys the forecast job,
writes the gateway URL into `web/config.js`, builds the React dashboard (`frontend/`, which
copies the call client and `config.js` into `frontend/dist`), deploys Hosting and Firestore rules, and seeds
the demo data. It prints the dashboard and call-client URLs at the end.

Check it worked:

```bash
curl "$(gcloud run services describe harvest-gateway --region $REGION --format 'value(status.url)')/healthz"
# {"ok":true,"store":"firestore","model":"..."}
```

Then open `https://$PROJECT.web.app/setup` (the old `setup.html` address redirects there).

## 6. Is it a one-time setup?

Section 4 is one-time. After that, every deploy is just re-running the script, and it is
safe to repeat. Three behaviours to know:

- **Seeding wipes data.** `deploy.sh` reloads the demo data at the end, which clears every
  Firestore collection first. That is right for the first deploy. For any later deploy set
  `SEED_DEMO_DATA=false` so live data survives. (The CI workflow already does.)
- **`--set-env-vars` replaces all variables.** The script passes the full set on every run,
  so always run it with the same `MILL_NAME` and so on. A new `JWT_SECRET` (made automatically
  when you pass none) signs everyone out; they just pick their role again. Pass the same
  `JWT_SECRET` every time to avoid that.
- **`web/config.js` is rewritten** with the Cloud Run URL. It shows up as a modified file in
  git afterwards. Do not commit it, or the local default (`apiBase: ""`) is lost.

Manual redeploy after a code change:

```bash
PROJECT=$PROJECT REGION=$REGION SEED_DEMO_DATA=false SKIP_API_ENABLE=true \
bash deploy/deploy.sh
git checkout web/config.js
```

## 7. Automatic deploys on push to `main`

`.github/workflows/deploy.yml` runs the tests, then runs `deploy/deploy.sh`, on every push to
`main` and on demand from the Actions tab. It authenticates with Workload Identity Federation,
so no service-account key is stored in GitHub.

The workflow only runs once the file is on `main`. Merge the branch that adds it, then push or
trigger it.

### One-time setup for the pipeline

Run with the variables from section 4 still set. `GH_REPO` is `owner/repo`.

```bash
export GH_REPO=RaymonddC/Harvest
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format='value(projectNumber)')

gcloud services enable iamcredentials.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com run.googleapis.com logging.googleapis.com \
  firebasehosting.googleapis.com firebaserules.googleapis.com

# 1. The account GitHub will act as
gcloud iam service-accounts create github-deployer --display-name="GitHub deployer"
SA=github-deployer@$PROJECT.iam.gserviceaccount.com

# 2. What it may do
for role in roles/run.admin roles/cloudbuild.builds.editor roles/artifactregistry.writer \
            roles/storage.admin roles/serviceusage.serviceUsageConsumer roles/logging.viewer \
            roles/firebasehosting.admin roles/firebaserules.admin; do
  gcloud projects add-iam-policy-binding $PROJECT --member=serviceAccount:$SA --role=$role --condition=None
done
# it deploys services that run as the runtime account, so it must be allowed to act as it
gcloud iam service-accounts add-iam-policy-binding $RUNTIME_SA \
  --member=serviceAccount:$SA --role=roles/iam.serviceAccountUser

# 3. Let this GitHub repository (and only it) act as that account
gcloud iam workload-identity-pools create github --location=global
gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location=global --workload-identity-pool=github \
  --issuer-uri=https://token.actions.githubusercontent.com \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='$GH_REPO'"
gcloud iam service-accounts add-iam-policy-binding $SA \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/attribute.repository/$GH_REPO"

# 4. The two values GitHub needs
echo "WIF_PROVIDER=projects/$PROJECT_NUMBER/locations/global/workloadIdentityPools/github/providers/github-provider"
echo "WIF_SERVICE_ACCOUNT=$SA"
```

### GitHub settings

In the repository: *Settings, Secrets and variables, Actions*.

| Type | Name | Value |
|---|---|---|
| Secret | `WIF_PROVIDER` | the `WIF_PROVIDER` line printed above |
| Secret | `WIF_SERVICE_ACCOUNT` | the `WIF_SERVICE_ACCOUNT` line printed above |
| Secret | `JWT_SECRET` | optional; a long random string (`openssl rand -hex 32`). Without it each deploy signs everyone out |
| Variable | `GCP_PROJECT` | your project id |
| Variable | `GCP_REGION` | e.g. `asia-southeast1` (defaults to that if empty) |
| Variable | `FIREBASE_WEB_CONFIG` | the JSON from section 4 step 7, or leave unset |
| Variable | `MILL_NAME`, `DEMO_LANGUAGE` | optional; defaults are in `deploy.sh` |

The first deploy (section 5) must be done by hand first. It seeds the data, and the workflow
deliberately never seeds.

### What a push does

1. `test` runs the backend tests on Python 3.12. If they fail, nothing is deployed.
2. `deploy` signs in to Google, installs the Firebase CLI and runs `deploy.sh` with
   `SEED_DEMO_DATA=false` and `SKIP_API_ENABLE=true`.
3. Pushes that land while a deploy is running wait their turn; they do not cancel it.

Optional: in *Settings, Branches*, protect `main` and require the *Backend tests* check, so
that only tested code reaches the deploy.

The Twilio phone channel is not wired into the workflow. To use it from CI, add the three
`TWILIO_*` values and the `REAL_CALL*` values as secrets/variables and pass them in the
workflow's `env:` block, as `deploy.sh` already reads them.

## 8. Day-to-day operations

- **Logs:** `gcloud run services logs read harvest-gateway --region $REGION --limit 100`
- **Reset the demo data:** sign in as Planner and press *Reset demo data* on the Setup page, or
  `TOKEN=$(curl -s -X POST $URL/api/auth/login -H 'Content-Type: application/json' -d '{"role":"planner"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')`
  then `curl -X POST $URL/api/demo/reset -H "Authorization: Bearer $TOKEN"`. It wipes Firestore, then reloads the seed.
- **Rotate the Gemini key (only with `GEMINI_BACKEND=api_key`):**
  `printf '%s' "$NEW_KEY" | gcloud secrets versions add gemini-api-key --data-file=-`, then
  redeploy so the service picks up `latest`.
- **Roll back the gateway:** Cloud Console, Cloud Run, `harvest-gateway`, *Revisions*, send
  100% of traffic to the previous revision.
- **Cost:** `--min-instances 1` keeps one instance warm and bills for it all day. After the
  hackathon run
  `gcloud run services update harvest-gateway --region $REGION --min-instances 0`, or delete
  the service.
- **Change the Gemini model:** set `LIVE_MODEL` on the service
  (`gcloud run services update harvest-gateway --region $REGION --update-env-vars LIVE_MODEL=...`).
  Note the next `deploy.sh` run will not carry this over, since it replaces all variables.

## 9. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `PERMISSION_DENIED` on `gcloud run deploy --source` in CI | The deployer lacks a role from the list in section 7. On newer projects Cloud Build runs as the Compute default account, which also needs `roles/cloudbuild.builds.builder`. |
| `Permission 'iam.serviceaccounts.actAs' denied` | The `serviceAccountUser` binding on the runtime account is missing. |
| Deploy succeeds but `/healthz` returns an error, or the logs show Firestore permission errors | Runtime account is missing `roles/datastore.user` (section 4 step 5). |
| Logs show `GOOGLE_API_KEY` missing or the voice call fails immediately | The secret does not exist, the runtime account cannot read it, or the key is wrong. |
| `firebase deploy` says the project is not a Firebase project, or hosting is not set up | Section 4 step 3 was skipped. |
| `firebase deploy` fails with 403 in CI | The deployer lacks `roles/firebasehosting.admin` or `roles/firebaserules.admin`. |
| Actions fail with 401, or the login page keeps reappearing | The session expired or `JWT_SECRET` changed or differs between instances. Pick the role again; set one `JWT_SECRET` for the service. |
| Buttons say "You are signed in as ..." or the server says your role is not allowed | Use *Switch user* in the header and pick someone whose role has that right (the planner has all of them). |
| Dashboard shows old pages or no role picker after a redeploy | Browsers cache. Pages, scripts and styles are served with `no-cache` (see `firebase.json`), but a copy fetched before that setting existed can stay for up to an hour: hard refresh (Ctrl+Shift+R) once. |
| The gateway has the wrong settings after a redeploy | The run used different env values than the last one. Re-run with the full set. |

## 10. Security notes

- Sign-in is demo mode: there is no password, so anyone who opens the URL can pick Planner. It
  only keeps honest users from clicking the wrong thing. Replace `/api/auth/login` with a real
  identity check (Firebase Auth) before any real data goes in.
- `JWT_SECRET` is stored as a plain Cloud Run environment variable. For anything beyond a demo,
  move it to Secret Manager and use `--set-secrets` as with the Gemini key.
- The gateway is deployed with `--allow-unauthenticated` (the browser must reach it) and CORS
  is `*` by default. Set `CORS_ORIGINS` to your Hosting URL for anything real.
- Firestore reads are public for the dashboard and the data is synthetic. Add Firebase Auth
  to the read rule in `firestore.rules` before using real data.
- Never commit `.env`, `.firebaserc` or any key file. All three are already in `.gitignore`.
