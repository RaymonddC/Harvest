# Decisions (task C-03)

| Question | Decision | Status |
|---|---|---|
| Browser call or real number? | Browser call (`web/call.html`) is the default. The real-phone channel (VA-8) is now built — see "The Twilio channel" below — but needs real Twilio credentials and `PUBLIC_BASE_URL` set before it does anything; nothing changes for the browser demo until those are set. | Decided |
| Crop | Palm fresh fruit bunches (FFB), Riau, Indonesia, per the design canvas | Default, change with `DEMO_CROP` |
| Language | Bahasa Indonesia (`DEMO_LANGUAGE`), with English caption lines (`CAPTION_TRANSLATE_TO`) | Confirm with the C-02 speech test |
| Prices | Floor Rp 2,900, reference 3,100, ceiling 3,350 per kg; first offer +4% (Rp 3,220), then steps of 2%. A counter inside the limits is accepted; above the ceiling goes to the planner | Illustrative; replace the reference with a published provincial FFB price |
| Target | 100 t per week; a week is a gap below 80 t (`GAP_TOLERANCE=0.2`) | Matches the wireframe |
| Buyer | "Koperasi Sawit Maju" (fictional), default planner user "Dewi" (a record on the Users page, not a setting) | `MILL_NAME` |
| Live model | `gemini-2.5-flash-native-audio-preview-12-2025` | Check it is still current before recording; set `LIVE_MODEL` |
| Dashboard auth | Sign-in with a username and password (salted PBKDF2-SHA256 hashes in the users collection, `app/access.py`), then a signed token. Roles are bundles of capabilities (closed set in code, roles and users stored in Firestore, edited on the Users page, where an admin sets usernames and passwords); every changing endpoint checks a capability (`app/auth.py`); reads, Firestore reads and the call client stay open because the data is synthetic | Changed 13 Oct from the no-password person picker (decided 10 Oct). The built-in accounts (dewi, budi, guest, farmer) share a demo password (`DEMO_PASSWORD`, default `harvest-demo`) that the sign-in page shows with one-click "use this account" buttons, because judges need a way in without an account. Viewer and farmer stay "demo" roles. Before real data: give real users their own passwords and empty `DEMO_PASSWORD` (which turns the demo accounts off). Firebase Authentication (task B-09) stays a Phase 2 option |

## Data model additions

The deck lists six collections. The build adds two:

- `rival_quotes`: the rival supplier's logged quote (supplier, crop, kg, price, delivery week).
- `campaigns/current`: campaign status for the dashboard.

`offers` also carries `deliver_week`, `from_week` and `harvest_id`, so an approved pull-forward
moves volume from the later week into the gap week instead of counting it twice. Offer status
can also be `escalated`, for a farmer request above the ceiling. It is held for the planner
and cannot be approved while it is outside the limits.

## Answer confidence

An answer is `firm` or `unsure`; unsure answers count for half in the forecast (`forecast.UNSURE_WEIGHT`).

## The Twilio channel (VA-8 stretch goal) — built, needs credentials to activate

`live_session.run_call` only talks to a `Channel` (see `live_session.py`): `accept`, `recv`,
`send_audio`, `send_control`, `close`, plus an `expected_channel` argument so each entry point
checks the call is actually meant for it. `BrowserChannel` wraps the browser's WebSocket (already
16k/24k mono PCM16, almost no work); `TwilioChannel` (`app/twilio_channel.py`) wraps Twilio Media
Streams. Neither needed any change to the negotiation/tool/retry code in `services.py`/`tools.py`.

What `TwilioChannel` does, from the earlier spec review:

- **Transcodes at its own edge.** `app/audio_codec.py` is a from-scratch G.711 mu-law codec plus a
  linear resampler (no `audioop` — deprecated since 3.11, gone in 3.13). Decode is verified
  byte-for-byte against `audioop.ulaw2lin` in `test_audio_codec.py`; encode is a nearest-neighbour
  lookup against that same decode table (hand-deriving the encode bit-packing directly got the
  segment/mantissa math subtly wrong on the first attempt — this sidesteps that entirely).
- **Sends Twilio's `clear` event on barge-in** — `send_control` forwards only `{"type":
  "interrupted"}` as Twilio's own `clear` message; everything else (captions, tool events, ended,
  error) has no screen on a phone call and is dropped, since it's already in the transcript
  `services.finish_call` saves.
- **Validates the Twilio request signature against `PUBLIC_BASE_URL`** in the new `/twilio/voice`
  webhook (`main.py`), never the request Cloud Run hands the app.
- **Waits for Twilio's `start` frame before sending audio** (`asyncio.Event`, not a buffer-and-hope)
  — Gemini's greeting can be ready before `start` is processed; buffering without a real wait raced
  against `run_call`'s own task-cancellation-on-first-completion and silently lost the greeting in
  testing. Worth remembering if this code gets copied elsewhere.
- **A dialer, not an "answer" button**: `POST /api/farmers/{id}/dial` (`services.dial_now`) places
  the outbound call via `twilio.rest.Client`, pointing its TwiML at `/twilio/voice`, which replies
  with `<Connect><Stream>` to `/twilio/stream/{call_id}`. `calls.channel` already carried which path
  a call is on (added ahead of this); both WS endpoints now refuse a call on the wrong channel.

To turn it on: set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` (a paid account —
trial accounts only dial pre-verified numbers) and `PUBLIC_BASE_URL` (the deployed Cloud Run URL).
`deploy/deploy.sh` wires `PUBLIC_BASE_URL` to the real URL automatically once it's known, if the
three Twilio vars are set. Nothing else changes if they're left blank.

A second, independent gate sits in front of `dial_now` itself: `REAL_CALLS_ENABLED` (default off)
and `REAL_CALL_ALLOWLIST` (comma-separated numbers — the only ones `dial_now` will ever actually
call). Being Twilio-configured is not enough on its own; both of these must also allow it. Set them
deliberately before testing — they're env vars, not a dashboard toggle, on purpose: nothing to
misclick live in front of an audience. For production (call anyone, not just test numbers), set
`REAL_CALL_ALLOWLIST=*` — the same wildcard convention `CORS_ORIGINS` already uses in this file.

Known, accepted gap: Twilio doesn't sign the Media Streams WebSocket handshake itself (only the
`/twilio/voice` webhook that sets it up) — `/twilio/stream/{call_id}`'s only protection is the
unguessable `call_id` and `run_call`'s own queued/channel checks. Fine for a hackathon demo; not
something to rely on for real traffic.

## Multi-crop campaigns (14 Oct)
One campaign per crop, keyed by crop. The default crop (`DEMO_CROP`, palm) keeps the ids it always had (campaign `current`,
forecast rows `W1`..`W5`), so existing data, tests and screens need no migration; other crops use their crop id (`rubber`,
`rubber-W1`). Each campaign has its own weekly target and weeks; a call runs with its crop's values (`services.settings_for_crop`).
`MULTI_CROP` is off by default (GitHub variable `MULTI_CROP=true` turns it on) until the dashboard's campaign screens use the picked crop; with it off the dashboard behaves exactly as before. Demo data stays palm only; a new crop needs farmers and price limits added by the planner,
and a gap-fill start refuses with a clear message while limits are missing.
