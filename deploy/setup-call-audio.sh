#!/usr/bin/env bash
# One-time setup of the private Cloud Storage bucket for call recordings (TODO item 14, step 2).
#
#   bash deploy/setup-call-audio.sh --check     # only shows what exists; changes nothing
#   bash deploy/setup-call-audio.sh             # creates or fixes whatever is missing; safe to run again
#
# Run it in Cloud Shell (signed in as someone who may create buckets and change IAM). It:
#   1. makes the bucket in Jakarta, private (no public access, uniform access control),
#   2. deletes recordings after RETENTION_DAYS + 1 days (the app stops playing them at RETENTION_DAYS),
#   3. turns off "soft delete", so a deleted recording is really gone (the default keeps it 7 more days),
#   4. lets the Cloud Run service's own account read, write and delete files in this bucket, and nothing else.
# It never deletes anything and never touches other buckets.
#
# Settings (environment variables, all optional):
#   PROJECT          default: the gcloud project            BUCKET         default: <project>-call-audio
#   BUCKET_LOCATION  default: asia-southeast2 (Jakarta)     RETENTION_DAYS default: 90
#   SERVICE / REGION default: harvest-gateway / asia-southeast1 (as in deploy.sh)
#   RUNTIME_SA       default: found from the running Cloud Run service
set -euo pipefail

CHECK=false
[[ "${1:-}" == "--check" ]] && CHECK=true

PROJECT="${PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
[[ -n "$PROJECT" ]] || { echo "Set PROJECT=<your project id> (or run: gcloud config set project <id>)" >&2; exit 1; }
BUCKET="${BUCKET:-${PROJECT}-call-audio}"
BUCKET_LOCATION="${BUCKET_LOCATION:-asia-southeast2}"
RETENTION_DAYS="${RETENTION_DAYS:-90}"
SERVICE="${SERVICE:-harvest-gateway}"
REGION="${REGION:-asia-southeast1}"
[[ "$RETENTION_DAYS" =~ ^[0-9]+$ && "$RETENTION_DAYS" -ge 1 ]] || { echo "RETENTION_DAYS must be a whole number of days" >&2; exit 1; }

say() { printf '%s\n' "$*"; }
do_it() { if $CHECK; then say "  (check only) would run: $*"; else "$@"; fi; }

say "Project $PROJECT | bucket gs://$BUCKET in $BUCKET_LOCATION | keep $RETENTION_DAYS days $($CHECK && echo '| CHECK ONLY')"

# The account the Cloud Run service runs as (deploy.sh sets none, so it is the project's default account).
RUNTIME_SA="${RUNTIME_SA:-$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" \
  --format='value(spec.template.spec.serviceAccountName)' 2>/dev/null || true)}"
if [[ -z "$RUNTIME_SA" ]]; then
  NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
  RUNTIME_SA="${NUMBER}-compute@developer.gserviceaccount.com"
  say "Service account: $RUNTIME_SA (the default one; the service was not found or sets none)"
else
  say "Service account: $RUNTIME_SA"
fi

say "1/4 Bucket"
if gcloud storage buckets describe "gs://$BUCKET" --project "$PROJECT" >/dev/null 2>&1; then
  have="$(gcloud storage buckets describe "gs://$BUCKET" --project "$PROJECT" --format='value(location)' | tr a-z A-Z)"
  say "  exists, location $have"
  [[ "$have" == "$(echo "$BUCKET_LOCATION" | tr a-z A-Z)" ]] || say "  WARNING: it is not in $BUCKET_LOCATION. A bucket cannot be moved; make a new one with another BUCKET name."
else
  do_it gcloud storage buckets create "gs://$BUCKET" --project "$PROJECT" --location "$BUCKET_LOCATION" \
    --default-storage-class STANDARD --uniform-bucket-level-access --public-access-prevention
fi

say "2/4 Delete after $((RETENTION_DAYS + 1)) days"
LIFECYCLE="$(mktemp)"
trap 'rm -f "$LIFECYCLE"' EXIT
printf '{"rule":[{"action":{"type":"Delete"},"condition":{"age":%d}}]}\n' "$((RETENTION_DAYS + 1))" > "$LIFECYCLE"
if $CHECK && ! gcloud storage buckets describe "gs://$BUCKET" --project "$PROJECT" >/dev/null 2>&1; then
  say "  (check only) would set the rule once the bucket exists"
else
  do_it gcloud storage buckets update "gs://$BUCKET" --project "$PROJECT" --lifecycle-file "$LIFECYCLE"
fi

say "3/4 Soft delete off (a deleted recording is gone, not kept 7 more days)"
if $CHECK && ! gcloud storage buckets describe "gs://$BUCKET" --project "$PROJECT" >/dev/null 2>&1; then
  say "  (check only) would turn it off once the bucket exists"
else
  do_it gcloud storage buckets update "gs://$BUCKET" --project "$PROJECT" --clear-soft-delete \
    || say "  could not change soft delete (an older gcloud?). Optional; the rest still works."
fi

say "4/4 Let $RUNTIME_SA use only this bucket"
if $CHECK && ! gcloud storage buckets describe "gs://$BUCKET" --project "$PROJECT" >/dev/null 2>&1; then
  say "  (check only) would grant roles/storage.objectUser once the bucket exists"
else
  do_it gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --project "$PROJECT" \
    --member "serviceAccount:${RUNTIME_SA}" --role roles/storage.objectUser >/dev/null
  say "  granted roles/storage.objectUser on gs://$BUCKET"
fi

say ""
say "Done. Bucket: gs://$BUCKET."
say "Next: set the GitHub Actions variable CALL_AUDIO_BUCKET=$BUCKET (and CALL_AUDIO_RETENTION_DAYS=$RETENTION_DAYS if not 90),"
say "then redeploy. Until that variable is set, Cloud Run does not record calls."
