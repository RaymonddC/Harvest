# Project audit, 16 Oct 2026

Four read-only reviews (backend security, call pipeline, dashboard, deploy and data protection). Items marked **checked** were
re-read in the code by the person who ran the audit; the rest are the reviewers' claims, to confirm when each is fixed.
Nothing here is fixed yet unless a line says "done". PDP Law items: see "Legal requirements" in `CLAUDE.md`.

## A. Before any real farmer is loaded
1. **Live data is readable without signing in** (**checked**). `/api/state`, `/api/stream`, the CSV exports and the PDFs need no token;
   `firestore.rules` lets anyone read `farmers`, `calls`, `messages` (phones, transcripts). Fix: sign-in on all `/api/*` reads, close the Firestore read rule.
2. **Public planner account** (**checked in part**). `DEMO_PASSWORD` defaults to `harvest-demo` in `deploy.sh`; `GET /api/auth/demo` returns it;
   the demo planner can call `POST /api/demo/reset` (reseeds the live database). Fix: empty by default in production, demo reset off there.
3. **`/ws/call/{call_id}` has no auth**; ids are `call-` + 8 hex characters and are listed in the public state. An outsider can take a queued call
   (fake consent, fake harvest or offer, Vertex spend). Fix: per-call token like the Twilio one, longer ids, origin check, cap on sockets.
4. **A refusal can become consent** (**checked**). `tools.py` `end_call` overwrites `session.consent` with the model's argument.
   Fix: refusal is sticky (False never becomes True); keep the consent time and notice version as proof (Art. 24).
5. **Transcripts are never deleted** (**checked**). The notice promises the transcript for N days; only audio expires. The transcript-only
   notice (used when recording is off) says no purpose and no days. Fix: retention sweep for `transcript`/`answers`, a "delete transcript" action,
   days and purpose in every notice, a test that the notice matches the retention setting.

## B. High: operations and cost
6. Calls stuck `on_call`/`queued` after a restart block phone campaigns and keep campaigns "running" (no reaper; `stop_campaign` leaves queued calls).
7. Cloud Run has no `--max-instances`, `--concurrency` or `--memory`; the recorder holds audio in memory (about 200 MB peak per ending call).
8. Retention drift: the bucket delete rule is set once by the script; the number in the notice comes from a deploy variable. Unsetting
   `CALL_AUDIO_BUCKET` silently turns recording off and the notice reverts. Fix: re-apply or check the rule in `deploy.sh`, print "recording off".
9. `create_offer`/`save_offer` do not validate `kg` (negative, NaN, over `MAX_OFFER_KG`) or the crop; `escalate=True` skips the price check.
10. `ToolHandlers.dispatch` catches only a few error types and runs on the event loop (one slow store call stalls every call's audio).

## C. Medium
- `finish_call` failure in `run_call`'s `finally` leaves the socket open and the campaign "running".
- Week rollover: UTC vs WIB (Sunday night/Monday morning), and `gap_week` stored as an index goes stale on Monday (store the date).
- A hang-up counts as dropped and queues a retry; the retry loses `campaign_id`.
- Gemini: quota error (1011) retries immediately and the raw exception text goes to the client; `open_live` retries without the language hint on any error.
- Re-adding or uploading a farmer erases `do_not_call`; a CSV `id` column can overwrite any farmer.
- No rate limits or daily dial caps; login has no throttle; a coordinator can widen the real-call allowlist (`campaign.run`).
- `JWT_SECRET` regenerated on every deploy, no minimum length; secrets are plain env vars (use Secret Manager).
- Twilio stream token checked only on `start`; malformed media frames can kill the call.
- Recording promised but store failed to open: no `audio_error` marker (the prompt uses `recording_enabled(settings)`).
- Answers and summary are stored and logged even without consent (tool calls log full args).
- Docs out of date: `DECISIONS.md` (recording "not built", "Opus", delete "to do"), `deploy.env.example` (job schedule says Monday, it is hourly).
- Twilio re-apply step in `deploy.sh` can fail and still exit 0. Dependencies unpinned; no Firestore backup (PITR/export).
- Pure-Python audio resampling on the event loop; CORS `*`; websocket origin not checked; `AUTH_REQUIRED=false` gives every request the planner.

## D. Dashboard (low)
ActButton has no catch; the recap's recording blob URL can leak if the panel closes during the fetch (and a 401 shows a generic message);
bulk approve stops partway without saying how many went through; several side fetches fail silently (`.catch(() => {})`); the shortcut keys work
under an open dialog; disabled controls often give no reason (`needs()` not used everywhere); token kept in localStorage for 12 h;
the 375 px layout was not measured.

## E. Test gaps
No tests for `FirestoreStore`, `firestore.rules`, the unauthenticated websocket, the demo-password endpoint when `DEMO_PASSWORD` is empty,
the `consent=false` end to end (nothing written to the audio store), or `deploy.sh` / `setup-call-audio.sh`.

## F. Reported by a user, not yet explained
"The agent has not finished talking but the voice ended." See TODO item 15.
