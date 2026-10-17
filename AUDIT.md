# Project audit, 16 Oct 2026

Four read-only reviews (backend security, call pipeline, dashboard, deploy and data protection). Items marked **checked** were
re-read in the code by the person who ran the audit; the rest are the reviewers' claims, to confirm when each is fixed.
Nothing here is fixed unless a line says "done". 17 Oct: the non-security, non-Twilio items marked done below were fixed (tests in `backend/tests/test_audit_fixes.py`). PDP Law items: see "Legal requirements" in `CLAUDE.md`.

## A. Before any real farmer is loaded
1. **Done 17 Oct.** Every `/api` call except sign-in (and the job, which has its own token) now needs a signed-in user (middleware `require_sign_in`); the dashboard gets its live data over a fetch stream that sends the token; downloads (CSV, PDF) go through `DownloadLink`; `firestore.rules` denies every browser read and write; the call page needs a session. Original finding: **Live data is readable without signing in** (**checked**). `/api/state`, `/api/stream`, the CSV exports and the PDFs need no token;
   `firestore.rules` lets anyone read `farmers`, `calls`, `messages` (phones, transcripts). Fix: sign-in on all `/api/*` reads, close the Firestore read rule.
2. **Deferred on purpose (17 Oct, the user's call): leave as is until the hackathon demo is over.** Do not load real farmers before this is fixed. Options when the demo ends: real accounts only, or demo buttons with a mandatory password and no demo reset. Finding: **Public planner account** (**checked in part**). `DEMO_PASSWORD` defaults to `harvest-demo` in `deploy.sh`; `GET /api/auth/demo` returns it;
   the demo planner can call `POST /api/demo/reset` (reseeds the live database). Fix: empty by default in production, demo reset off there.
3. **Done 17 Oct (browser socket).** `POST /api/calls/{id}/token` (signed in, call waiting) hands a per-call token that `/ws/call/{id}?token=` requires (HMAC on `JWT_SECRET`). Not done: the Twilio stream token is still only checked on `start`; origin check; cap on sockets. Original: **`/ws/call/{call_id}` has no auth**; ids are `call-` + 8 hex characters and are listed in the public state. An outsider can take a queued call
   (fake consent, fake harvest or offer, Vertex spend). Fix: per-call token like the Twilio one, longer ids, origin check, cap on sockets.
4. **Done 17 Oct.** A refusal is sticky (`ToolHandlers._set_consent`); the call stores `consent_proof` (time of the answer, language, notice type, days). Original: **A refusal can become consent** (**checked**). `tools.py` `end_call` overwrites `session.consent` with the model's argument.
   Fix: refusal is sticky (False never becomes True); keep the consent time and notice version as proof (Art. 24).
5. **Done 17 Oct.** Every transcript notice says the days and the purpose; calls store `transcript_expires_at`; `purge_expired_transcripts` runs when a call finishes and in the weekly job; planners can delete one now (`DELETE /api/calls/{id}/transcript`, button in the recap). Not done: erasing a farmer's calls when the farmer is deleted (decided: no). Original: **Transcripts are never deleted** (**checked**). The notice promises the transcript for N days; only audio expires. The transcript-only
   notice (used when recording is off) says no purpose and no days. Fix: retention sweep for `transcript`/`answers`, a "delete transcript" action,
   days and purpose in every notice, a test that the notice matches the retention setting.

## B. High: operations and cost
6. **Done (browser calls):** `services.reap_stale_calls` closes `on_call` calls older than `MAX_CALL_SECONDS`+3 min and `queued` calls older than 12 h, run from `refresh_campaign_status`. Not done: phone calls (left to Twilio's status callback) and `stop_campaign` leaving queued calls.
7. **Done:** `deploy.sh` now sets `--max-instances 10 --concurrency 20 --memory 1Gi --cpu-boost` (overridable). Original finding: no limits; the recorder holds audio in memory (about 200 MB peak per ending call).
8. Retention drift: the bucket delete rule is set once by the script; the number in the notice comes from a deploy variable. Unsetting
   `CALL_AUDIO_BUCKET` silently turns recording off and the notice reverts. Fix: re-apply or check the rule in `deploy.sh`, print "recording off".
9. **Done:** volume must be finite, positive, at most `MAX_OFFER_KG` (create_offer, check_offer NaN), `save_offer` cannot exceed the kg `check_offer` priced, crop names are validated. Original: `create_offer`/`save_offer` do not validate `kg` (negative, NaN, over `MAX_OFFER_KG`) or the crop; `escalate=True` skips the price check.
10. **Done:** any tool error becomes an `error` result and tools run in `asyncio.to_thread`. Original: `ToolHandlers.dispatch` catches only a few error types and runs on the event loop (one slow store call stalls every call's audio).

## C. Medium
- **Done:** `finish_call` failure in `run_call`'s `finally` no longer skips telling the browser or closing; a failed deal text no longer skips the retry or campaign status.
- **Done:** the mill's clock (`config.today_local`, WIB) is used for planning weeks and "today"; calls keep `gap_week_start` and find their week by date (`services.call_gap_week`).
- **Done in part:** the retry keeps `campaign_id` and the week date. Still open: a hang-up after an explicit no still counts as dropped and retries.
- **Done in part:** `open_live` no longer retries on quota/auth errors; the client gets a generic message; an empty Live stream no longer spins. Still open: a quota failure still queues a normal retry call.
- **Done in part:** re-adding a farmer keeps `do_not_call`. Still open (security): a CSV `id` column can overwrite any farmer.
- No rate limits or daily dial caps; login has no throttle; a coordinator can widen the real-call allowlist (`campaign.run`).
- `JWT_SECRET` regenerated on every deploy, no minimum length; secrets are plain env vars (use Secret Manager).
- Twilio stream token checked only on `start`; malformed media frames can kill the call.
- Recording promised but store failed to open: no `audio_error` marker (the prompt uses `recording_enabled(settings)`).
- Answers and summary are stored and logged even without consent (tool calls log full args).
- Docs out of date (open): `DECISIONS.md` (recording "not built", "Opus", delete "to do"), `deploy.env.example` (job schedule says Monday, it is hourly).
- Twilio re-apply step in `deploy.sh` can fail and still exit 0. Dependencies unpinned; no Firestore backup (PITR/export).
- Pure-Python audio resampling on the event loop; CORS `*`; websocket origin not checked; `AUTH_REQUIRED=false` gives every request the planner.

## D. Dashboard (low). **Done 17 Oct:** ActButton catch, recording blob URL and abort, bulk approve count, shortcuts under dialogs, disabled-reason titles in two places, failed-load notes for the track record and approval impact. Still open: token in localStorage, other silent fetches, 375 px check.
ActButton has no catch; the recap's recording blob URL can leak if the panel closes during the fetch (and a 401 shows a generic message);
bulk approve stops partway without saying how many went through; several side fetches fail silently (`.catch(() => {})`); the shortcut keys work
under an open dialog; disabled controls often give no reason (`needs()` not used everywhere); token kept in localStorage for 12 h;
the 375 px layout was not measured.

## E. Test gaps
No tests for `FirestoreStore`, `firestore.rules`, the unauthenticated websocket, the demo-password endpoint when `DEMO_PASSWORD` is empty,
the `consent=false` end to end (nothing written to the audio store), or `deploy.sh` / `setup-call-audio.sh`.

## F. Reported by a user, not yet explained
"The agent has not finished talking but the voice ended." See TODO item 15.

## G. Added 17 Oct: a farmer names a week that is already full
Built (not from the audit): `services.week_fill` / `next_week_with_room` (a week is full when expected supply plus waiting offers reach the target, or the mill's
weekly capacity; the farmer's own record is not counted against them). `record_harvest` answers `week_full` once per date: nothing is saved, the agent offers the
nearest later week within three weeks that has room, and if the farmer keeps the date the next call saves it with a `week_full` flag on the harvest.
`decide_offer` refuses (HTTP 409) to approve an offer into a week that filled meanwhile; the planner can choose "Approve anyway" (`?allow_full=true`).
Bulk "Approve all" skips those offers and says so. Not done: showing the `week_full` flag on the dashboard's harvest or surplus views.
