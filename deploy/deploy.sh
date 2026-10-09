#!/usr/bin/env bash
# Deploy the voice gateway (Cloud Run service), the forecast job (Cloud Run job),
# Firestore rules and the dashboard (Firebase Hosting).
#
# Needs: gcloud and firebase CLIs, logged in; a Firestore database in Native mode;
# a secret named gemini-api-key in Secret Manager.
#
#   PROJECT=my-project REGION=asia-southeast1 FIREBASE_WEB_CONFIG='{"apiKey":...}' deploy/deploy.sh
#
# VA-8 stretch goal (the real phone channel): also set TWILIO_ACCOUNT_SID and
# TWILIO_FROM_NUMBER, and first create a secret named twilio-auth-token:
#   gcloud secrets create twilio-auth-token --data-file=- <<< "$TWILIO_AUTH_TOKEN"
# It still won't dial anyone without REAL_CALLS_ENABLED=true and REAL_CALL_ALLOWLIST
# set too - that gate is deliberate, see DECISIONS.md.
set -euo pipefail

: "${PROJECT:?Set PROJECT to your GCP project id}"
REGION="${REGION:-asia-southeast1}"
SERVICE="${SERVICE:-harvest-gateway}"
JOB="${JOB:-harvest-forecast}"
MILL_NAME="${MILL_NAME:-Koperasi Sawit Maju}"
PLANNER_NAME="${PLANNER_NAME:-Dewi}"
DEMO_LANGUAGE="${DEMO_LANGUAGE:-Bahasa Indonesia}"
PLANNER_TOKEN="${PLANNER_TOKEN:-}"
# VA-8 stretch goal: set all three to enable the real-phone channel. PUBLIC_BASE_URL
# is set automatically below once the Cloud Run URL is known - no need to pass it.
TWILIO_ACCOUNT_SID="${TWILIO_ACCOUNT_SID:-}"
TWILIO_AUTH_TOKEN="${TWILIO_AUTH_TOKEN:-}"
TWILIO_FROM_NUMBER="${TWILIO_FROM_NUMBER:-}"
REAL_CALLS_ENABLED="${REAL_CALLS_ENABLED:-false}"
REAL_CALL_ALLOWLIST="${REAL_CALL_ALLOWLIST:-}"
# Seeding wipes every Firestore collection and reloads the demo data. Leave it on for the first
# deploy, turn it off (SEED_DEMO_DATA=false) for every redeploy and in CI so live data survives.
SEED_DEMO_DATA="${SEED_DEMO_DATA:-true}"
# One-time API enablement needs more permission than a deploy; CI sets SKIP_API_ENABLE=true.
SKIP_API_ENABLE="${SKIP_API_ENABLE:-false}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

gcloud config set project "$PROJECT" >/dev/null
if [[ "$SKIP_API_ENABLE" != "true" ]]; then
  gcloud services enable run.googleapis.com firestore.googleapis.com secretmanager.googleapis.com \
    cloudbuild.googleapis.com artifactregistry.googleapis.com logging.googleapis.com
fi

# "^@^" switches gcloud's list delimiter to @, because the Firebase config JSON contains commas.
ENV_VARS="^@^STORE_BACKEND=firestore@GOOGLE_CLOUD_PROJECT=$PROJECT@SEED_ON_START=false"
ENV_VARS="$ENV_VARS@MILL_NAME=$MILL_NAME@PLANNER_NAME=$PLANNER_NAME@DEMO_LANGUAGE=$DEMO_LANGUAGE"
[[ -n "$PLANNER_TOKEN" ]] && ENV_VARS="$ENV_VARS@PLANNER_TOKEN=$PLANNER_TOKEN"
if [[ -n "${FIREBASE_WEB_CONFIG:-}" ]]; then ENV_VARS="$ENV_VARS@FIREBASE_WEB_CONFIG=$FIREBASE_WEB_CONFIG"; fi

# WebSocket calls: long timeout, session affinity, one warm instance for the demo.
gcloud run deploy "$SERVICE" --source "$ROOT/backend" --region "$REGION" \
  --allow-unauthenticated --timeout 3600 --session-affinity --min-instances 1 \
  --set-env-vars "$ENV_VARS" --set-secrets GOOGLE_API_KEY=gemini-api-key:latest

gcloud run jobs deploy "$JOB" --source "$ROOT/backend" --region "$REGION" \
  --command python --args=-m,app.forecast_job \
  --set-env-vars "STORE_BACKEND=firestore,GOOGLE_CLOUD_PROJECT=$PROJECT"

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format 'value(status.url)')"
echo "Gateway: $URL"

if [[ -n "$TWILIO_ACCOUNT_SID" && -n "$TWILIO_AUTH_TOKEN" && -n "$TWILIO_FROM_NUMBER" ]]; then
  echo "Wiring up the Twilio channel (PUBLIC_BASE_URL=$URL, REAL_CALLS_ENABLED=$REAL_CALLS_ENABLED)..."
  gcloud run services update "$SERVICE" --region "$REGION" --update-env-vars \
    "^@^PUBLIC_BASE_URL=$URL@TWILIO_ACCOUNT_SID=$TWILIO_ACCOUNT_SID@TWILIO_FROM_NUMBER=$TWILIO_FROM_NUMBER@REAL_CALLS_ENABLED=$REAL_CALLS_ENABLED@REAL_CALL_ALLOWLIST=$REAL_CALL_ALLOWLIST" \
    --set-secrets TWILIO_AUTH_TOKEN=twilio-auth-token:latest
fi

# Point the dashboard at the gateway. WebSockets do not pass through Hosting rewrites,
# so the browser talks to Cloud Run directly.
FB="${FIREBASE_WEB_CONFIG:-null}"
NEEDS_TOKEN=$([[ -n "$PLANNER_TOKEN" ]] && echo true || echo false)
cat > "$ROOT/web/config.js" <<JS
window.HARVEST_CONFIG = {
  apiBase: "$URL",
  millName: "$MILL_NAME",
  plannerName: "$PLANNER_NAME",
  firebase: $FB,
  needsToken: $NEEDS_TOKEN,
};
JS

(cd "$ROOT" && firebase deploy --only hosting,firestore:rules --project "$PROJECT")

if [[ "$SEED_DEMO_DATA" == "true" ]]; then
  echo "Seeding demo data (this replaces everything in Firestore)..."
  curl -fsS -X POST "$URL/api/demo/reset" ${PLANNER_TOKEN:+-H "X-Planner-Token: $PLANNER_TOKEN"} >/dev/null
else
  echo "Skipping demo data (SEED_DEMO_DATA=false)."
fi
echo "Done. Dashboard: https://$PROJECT.web.app/setup.html  Call client: https://$PROJECT.web.app/call.html"
