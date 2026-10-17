# TODO: code vs. README mismatches (found 2026-10-09)

Fix later. Items 1 and 2 matter most for the "a human approves every deal" claim.

1. ~~**Escalated offers can be approved at the ceiling.**~~ Fixed 2026-10-10: approving an
   escalated offer now checks `requested_price` against the limits and approves at that price
   (undo restores the quoted ceiling). Test: `test_escalated_offer_needs_limits_that_cover_the_request`.
   `tools.py` `_tool_save_offer` (escalate branch) stores `max(quoted)`, which is the ceiling,
   as `price_per_kg`. `services.decide_offer` and the Approve button in `web/js/approvals.js`
   only check `price_per_kg` against the limits, so an escalated offer always passes.
   The "Above the ceiling, raise the ceiling or reject" warning only shows if the agent never
   called `check_offer`. Fix: store or check `requested_price`, or block approval of escalated
   offers until the limits cover it. See `tests/test_tools.py:81-89`.

2. ~~**Confirmation call can be marked confirmed when the farmer wanted changes.**~~ Fixed 2026-10-10:
   only outcome `completed` confirms; the prompt tells the agent to use `escalated` for changes.
   Test: `test_only_a_completed_confirmation_call_marks_the_offer_confirmed`. Original problem:
   `services.finish_call` sets `confirmed_by_voice=True` for any clean ending that is not
   `declined` or `stopped` (so `escalated` and `wrong_person` count too). Fix: require an
   explicit outcome for confirm calls.

3. ~~**"Agent never sees the limits" is not strictly true.**~~ Fixed 2026-10-10 by rewording the README
   row and the `prompt.py` docstring: the agent only gets the next price it may say, never the range.
   Original problem: `check_offer` returns the ceiling on
   `escalate` and the floor on a below-floor counter. Either fix the README and the `tools.py`
   docstring, or stop returning the number.

4. ~~**Read-back before saving is a prompt rule only.**~~ Fixed 2026-10-10: `CallSession.read_back`
   remembers the last numbers read back per crop and `record_harvest` refuses to save different ones.
   Test: `test_record_harvest_refuses_to_save_without_a_matching_read_back`. Original problem: `record_harvest` saves if the model sends
   `confirmed_by_farmer=true` without the unconfirmed call first. Fix: track the read-back in
   `CallSession` and refuse otherwise.

5. ~~**Counters inside the limits are accepted immediately**~~ Decided 2026-10-10: intended; stated in the README.

6. ~~**Docs:** AI disclosure and "read the reference price first" are prompt-only.~~ Fixed 2026-10-10: the README now says so.

## Login (decided 10 Oct: keep the demo role picker for the hackathon)

7. **Replace the demo role picker with Firebase Authentication** (plan task B-09, Phase 2).
   *13 Oct: sign-in now takes a username and password (hashed); the built-in accounts share the
   `DEMO_PASSWORD` shown on the sign-in page. Before real data, give users their own passwords and
   empty `DEMO_PASSWORD`. Firebase Authentication below is still the Phase 2 option.*
   Google sign-in on the pages, the server verifies each request's ID token and checks an email
   allow list, and the Firestore read rule requires a signed-in user. Do it before any real data
   or real phone calls, and after the submission. Replace `/api/auth/login` in
   `backend/app/main.py` and `backend/app/auth.py`; the frontend gate is in `web/js/data.js`.
   Offers now record the approving user (`decided_by`, `decided_by_id`); link users to real accounts by
   email. RBAC without real sign-in is only labels, so this is what makes the roles protection.
   Also add an audit log of who did what and of refused attempts (Honeypot has one in `core/audit.py`),
   and a screen to edit roles if a mill needs custom ones.

8. **After judging, shut the public demo down.** Anyone with the URL can pick Planner, start
   campaigns, reset the demo data and use the Gemini quota. Scale the gateway to zero
   (`gcloud run services update harvest-gateway --region $REGION --min-instances 0`) or delete it,
   and switch the *Deploy* workflow off.

9. **Keep the plan doc and board in step with these decisions** (10 Oct), so the team and judges read
   the same thing:
   - Login: the Technical spec and issue #16 still say Firebase login; they should say "demo role picker".
   - No build freeze: issue #18's title ("freeze the build"), the plan's feature freeze on 15 Oct and its
     "nothing new after 15 October" rule no longer apply. Instead, after the last rehearsal tag what you
     submit (`git tag submission-v1`) and re-check the live site after any later deploy.

## Open: the microphone is silent on real devices (10 Oct, not solved)

10. **Root cause found 2026-10-10, fix pushed (confirm on a real call).** `web/js/audio-worklets.js` re-created
    its buffer with the length of the buffer it had just sent, which is 0 once sent, so the microphone
    produced one chunk and stopped (the call page said `chunks made: 1, sent: 0`). Test:
    `tests/test_worklet.py`. The notes below are the investigation before that.

    **The call connects and the agent speaks, but the browser's microphone stays silent.** The "You"
    meter does not move, the page warns `No sound from "Default" yet`, the agent never gets an answer
    and there is no farmer transcript. Seen on the live site and locally, on Windows (Brave) and on
    Android (Brave and Chrome).
    - **Ruled out:** the Gemini key (the agent speaks, so it works), the Live model, a Brave-only
      problem (Chrome behaves the same), a paused audio engine (`resume()` added), and the capture
      code itself (in headless Chromium with a fake microphone a tone fills the meter and silence
      leaves it empty).
    - **Not yet tried or not reported back:** the text in the `/mic-test.html` info box and whether
      its 3-second playback is clear; a plain voice-recorder app on the same phone; the Android
      permission (Settings, Apps, browser, Permissions, Microphone) and the microphone privacy switch;
      a wired headset; the Windows Sound input meter; another computer or phone; Firefox.
    - **Added 2026-10-10:** a "Plain" audio option in `/mic-test.html` (no constraints at all), and a
      gateway log line per call, `microphone input: N chunks, B bytes, peak P of 32767`. Peak near 0
      with many chunks means the browser sent silence. Read it with
      `gcloud run services logs read harvest-gateway --region $REGION --limit 100 | grep microphone`.
    - **Tools that exist:** `/mic-test.html`, the Microphone name in the call page's warning, the
      Agent / You meters, and the Volume slider.

11. **Voice follow-ups (parked 10 Oct).** The microphone now works (item 10). Still to check on a real call:
    - Reply speed after the new Live model (`-12-2025`) and `VAD_SILENCE_MS=400`. If the agent cuts the
      farmer off, raise `VAD_SILENCE_MS` in `config.py` to 700 to 1000. If the call fails to connect,
      revert the `realtime_input_config` block in `live_session.build_live_config`.
    - The Gemini key is on the free tier (20 text requests a day per model), so caption translation and the
      forecast note stop after a few calls. Fix: enable billing on the AI Studio project that owns the key
      (https://aistudio.google.com/apikey), or switch to `GEMINI_BACKEND=vertex`.
    - The agent's opening is partly English, partly the farmer's language (`backend/app/prompt.py`).
    - Farmer list: Delete is permanent (a confirm popup, no undo; accepted).

12. **Demo resilience (done 12 Oct, on Vertex AI).** Built: the Demo guide in the sidebar, a recorded sample call with
    sound (`web/samples/gap-fill.json` plus `web/samples/clips/`, replay engine in `web/js/call.js`), and the
    **Play the farmer for me** button on the call page (sends the clips in `web/samples/farmer-lines.json` into a live
    call, one line after each agent reply; see `backend/scripts/sample_call.py` to re-record). Rebuild the sample with:
    `cd backend && python scripts/sample_call.py clips` (only new lines), `record` (needs a Vertex token), `build <run dir>`.
    - Vertex us-central1 names that work: `gemini-live-2.5-flash-native-audio` (Live), `gemini-2.5-flash` and
      `gemini-2.5-flash-lite` (text), `gemini-2.5-flash-tts`, `gemini-2.5-flash-preview-tts` and
      `gemini-2.5-pro-preview-tts` (speech). Not available: `gemini-live-2.5-flash-preview-native-audio-09-2025`.
      Note `.env.example` still says `TEXT_MODEL=gemini-3.8-flash`; that name was not checked on Vertex.
    - Measured reply delay (end of the farmer's last audio chunk to the agent's first audio, at the gateway,
      `VAD_SILENCE_MS=400`), 6 scripted calls, per farmer turn: 1.5 to 1.8 s (name and consent), 1.3 to 1.4 s (volume),
      1.8 to 2.0 s (read-back, sometimes a `record_harvest` first), 1.4 to 2.4 s (counter-offer, `check_offer`), 1.8 to 3.0 s (final
      yes, `save_offer` and `end_call`); about 0.4 s less without the VAD wait. Connect to first agent audio: 1.35 to 2.7 s. A browser adds network and buffering.
    - Prompt problems seen in the recordings, **fixed 14 Oct and checked on 12 real scripted calls**: (1) a counter price
      ("naik jadi 3300") saved as a 3,300 kg harvest (2 of 6 calls before, 0 of 12 after): the prompt separates prices from
      weights, and `record_harvest` refuses a second, different volume that falls in the crop's price range (once; the same
      number again goes through); (2) English in the middle of Indonesian: 0 of 12 after ("Speak only {language}"; one stray
      "permission" came from the English opening sentence in the prompt, once); (3) the consent question repeated: once
      per call in 12 of 12; (4) `end_call` not always called: called in 12 of 12 ("Ending the call" rules).
      Found on the way: the agent often sent `record_harvest` with `confirmed_by_farmer: true` first, so the volume was
      never saved (0 of 4 calls). The tool now turns that call into the read-back step (no error) and the prompt says "two
      calls, false then true"; the volume is now saved in about half the calls (the agent often stops after the
      read-back). In gap-fill calls the volume is already on record and the offer is unaffected; in collect calls it
      matters, so test a collect call (the script records gap-fill only) before relying on it.
    - **Transcript and goodbye (14 Oct, found by a planner on the live site; fixed and checked on real calls).**
      (1) The speech-to-text had no language hint, so the Live API detected the language itself and came back with Korean
      ("야 야 야, 야 야 됐거든") and Turkish ("Kıyafet uykusu") for noisy Indonesian speech, and German on the live site, although
      the agent understood. The farmer's language is now sent as `language_codes` (`live_session.LANGUAGE_CODES`); Vertex accepts
      it. Measured on noisy synthetic speech: "iya itu benar, masih setuju" was right 3 of 3 with the hint and wrong-language
      3 of 3 without. Limits: on the repetitive "ya ya ya, ya ya betul betul betul" in noise the hinted transcript is often
      empty (better than wrong, still not right); `custom_vocabulary` added nothing. If the service rejects the setup the call
      reconnects without the hint (`open_live`). (2) After `end_call` the agent sometimes repeated the whole deal (13.6 s of
      speech in 1 of 12 recorded calls; normally a 2 s goodbye): the prompt says everything before `end_call` and one short
      goodbye after, and the server lets at most 5 s of speech through after it (`GOODBYE_MAX_AUDIO_SECONDS`), because audio
      arrives faster than it plays. Checked on 3 real confirmation calls: farmer lines transcribed correctly, call ended 1 to
      1.6 s after `end_call`, 0.1 to 2.8 s of speech after it, all confirmed by voice.
    - **Vertex Live quota:** running 6 or more Live sessions at once (or about 25 in a few minutes) returned
      `1011 Resource exhausted` for every session for a while. Fine for a demo with one call at a time; do not run parallel
      test calls, and ask for a quota increase on the project if a campaign will run several calls together.
    - The stand-in farmer now picks its line from what the agent just said (`web/js/stand-in.js`, rules in
      `web/samples/farmer-lines.json`: `when`, `after`, `max`, `ends`, `fallback`), so it keeps its sense when the agent varies
      its order; it says goodbye and switches itself off. It reuses "Ya, benar." as the short fallback; a dedicated
      "Ya, silakan, Pak." clip would sound better (add it to the json and run `sample_call.py clips`).

13. **Multi-crop campaigns (done 14 Oct; C-05).** One campaign per crop: `POST /api/campaigns`, `/api/campaigns/{id}/start|stop`,
    per-crop forecast rows (`W1` for the default crop, `rubber-W1` for others), `settings.multi_crop` (env / GitHub variable
    `MULTI_CROP`, on by default, `false` is the kill switch). The dashboard screens use the picked crop. A new crop needs farmers
    (CSV with a `crop` column) and a price range on the Setup page before a gap-fill call can start; the demo data stays palm only.
    Not built: removing a campaign, renaming one, per-crop gap tolerance.

14. **Call audio recording (decided 15 Oct; step 1 built 15 Oct; off until `CALL_AUDIO_DIR` is set).** See "Call audio recording" in
    `DECISIONS.md` for what, who, how long and the law and cost notes. **Built (step 1):** `app/call_audio.py` (a recorder that puts both
    sides on the call's clock, a stereo MP3 encoder, a local-folder store with the 90-day clean-up), wired into `run_call` (kept only
    when the farmer consented; a failure never stops a call finishing), `GET /api/calls/{id}/audio` (capability `calls.listen`, planner
    only, 410 after the retention period), a start time (`t`) on every transcript line, the consent notice switching to the recording
    wording when a folder is set, and an audio player with click-to-jump times in the call recap. **Step 2 built 16 Oct (untested against real Google Cloud):** `GcsAudioStore` (`CALL_AUDIO_BUCKET`, passed by `deploy.sh` and the workflow),
    the bucket script `deploy/setup-call-audio.sh` (Jakarta, private, delete after 91 days, soft delete off, only the Cloud Run account may use it; run it
    with `--check` first), and a planner's "Delete recording" button (`DELETE /api/calls/{id}/audio`; the transcript stays). **Still to do:** run the
    script, set the `CALL_AUDIO_BUCKET` variable, and check the real thing on a live call (the tests use fake calls and a fake bucket). Before real use:
    a lawyer checks the consent wording, and a native speaker checks the Javanese and Sundanese notices.
    **Consent wording now follows the call's language** (done 15 Oct, `prompt.NOTICES`): fixed sentences for the greeting (says it is an
    AI), the identity question and the consent question in each of the five languages, instead of English for the model to translate.
    Checked in tests only; not yet checked with a real call.

15. **Real phone calls over Twilio (code done 16 Oct, needs an account to test).** Status callback, stream token,
    retry handling, "Call by phone…" in the farmer menu and the deploy wiring are built and tested with fakes (see "The Twilio
    channel" in `DECISIONS.md`). To try it: a Twilio account and voice number, Indonesia allowed in Voice Geographic
    Permissions, the `twilio-auth-token` secret, the four GitHub variables, then dial your own (verified) phone. Check on that
    call: audio quality at 8 kHz, reply delay, barge-in, and that a missed call ends as dropped.

16. **Harvest calls save the volume reliably (A-04, done 16 Oct).** Measured with `backend/scripts/harvest_call_test.py`
    (real Live model on Vertex, scripted text farmer, Pak Rahmat): before 7 of 8 calls saved the harvest (the failure: the
    agent read the same numbers back over and over and never saved them); after 10 of 10, end_call in 10 of 10. Fixes in
    `tools.py`: a repeated read-back of the same numbers answers "already read back, save it now"; the first end_call is refused
    once while a read-back is unsaved (the second always ends the call); every read-back is written to the call
    (`harvest_read_back`) so a dropped call keeps it, and the call recap offers **Save this harvest**
    (`POST /api/calls/{id}/confirm-harvest`). Also: `check_offer` refuses when the farmer's harvest is not after the gap week
    (nothing to bring forward), which the run showed the agent doing. Text farmer, not speech: still check one spoken call.

17. **Business loop (code done 16 Oct, branch `claude/business-loop`).** Five additions:
    - **Deliveries, forecast accuracy, farmer reliability** (`track_record.py`): promises are snapshotted each week, deliveries
      come in by CSV (Forecast page, "Record deliveries") or one at a time on a farmer's page; the Forecast page shows accuracy
      and the supply likely given each farmer's record. Demo seed has 4 finished weeks for the baseline farmers.
    - **Impact before approving** (`GET /api/approvals/impact`): each waiting offer shows the weeks after approval, its cost,
      premium over the reference, rival comparison and any new gap.
    - **Harvest rounds**: the agent asks how often the farmer harvests (`every_days`, 5 to 45); later rounds are projected
      into the forecast. Offers keep calendar weeks so they stay right when the weeks roll.
    - **Rolling weeks and the Monday job** (`PLAN_START_AUTO`, `POST /api/jobs/weekly` with `JOB_TOKEN`, Cloud Scheduler
      `harvest-weekly` at 06:00 Jakarta): snapshots promises, sends gap alerts and the offers digest, starts campaigns with
      "Call every Monday" on. To enable live: set the GitHub secret `JOB_TOKEN`.
    - **Text confirmation and planner alerts** (`messaging.py`): a written deal confirmation after the voice confirmation,
      alerts for new gaps and waiting offers, all kept in the outbox (Approvals page). Sent over Twilio only when
      `MESSAGING_CHANNEL` is `sms` or `whatsapp` and the number is allowlisted; the Twilio number needs A2P registration
      (SMS) or a WhatsApp sender first. The new language templates need a native speaker's check.

18. **Campaigns, farmer database, calendar, calls and agent pages (code done 16 Oct, branch `claude/campaigns-calendar`).**
    A crop can have several campaigns, each with its own farmers (`farmer.campaign_id`, one campaign per farmer; farmers
    from before belong to their crop's first campaign; `null` = farmer database only). Campaigns can be renamed, re-targeted
    and removed. New pages: Farmers (every farmer, move between campaigns), Agent (persona and questions, moved off Setup),
    Calls (the call client embedded as `call.html?embed`, next to the campaign's calls), Calendar (`GET /api/calendar`:
    planning weeks, calls made and planned, Monday calls, harvests with projected rounds, deal weeks, deliveries). Setup is
    now "Campaign". Price ranges stay per crop (campaigns of one crop share them).

19. **Simpler dashboard and campaign dates (code done 17 Oct, branch `claude/flow-nav`).** The sidebar follows the
    planner's flow (1 Prepare, 2 Call, 3 Watch, 4 Decide), with Agent under Settings and Users in the account menu; each
    page opens with its step and the next page; the menu collapses to icons. Campaigns run from a start date to an end
    date (`start_date`, `end_date`): the forecast shows week 1 (next week) up to the end, at most 12 weeks; weeks before a
    later start are greyed out and never short. Older campaigns with only `weeks` still work. Fixed: chart bar layers drawn
    as white pills (CSS class clash with the calendar toggle), projected rounds not drawn, phone pages scrolling sideways.

20. **Mill operations (code done 17 Oct, branch `claude/mill-operations`).** The forecast shows supply by day, week,
    month or year (`GET /api/supply`: expected, net deliveries, target, capacity, truck loads). Campaigns have the mill's
    capacity per day, working days and truck load; weeks over capacity are a surplus with the farmers to move a week
    later (texted). Deliveries carry weighbridge grading (unripe, dirt, other), the net weight and the price from the
    matched purchase order, with a goods receipt and payment PDF. Official farmgate prices (Disbun) can drive the price
    range. Farmers have plot location, area and certification; a traceability summary and CSV flag farmers who deliver
    more than their plot can grow. Still to do: real Disbun price import (no public API found; entered by hand), voice
    calls that ask farmers to deliver later (today the planner agrees it and the farmer gets a text), plot polygons.

21. **Adjustable automatic calls, clearer Campaign page, more demo campaigns (17 Oct, same branch).** Each campaign's
    automatic calls run on chosen weekdays at a chosen hour (Asia/Jakarta); Cloud Scheduler now calls
    `/api/jobs/weekly` every hour (`scheduled_calls`), which does the weekly bookkeeping once a week from Monday 06:00
    and starts the campaigns due that hour (`/api/jobs/run-all` runs everything by hand). The redeploy updates the
    scheduler job. Wording now says calls are outbound and the browser is a demo phone. Demo data adds "Palm, Kampar"
    and "Rubber" with their own farmers, history and a waiting offer (`load_seed(..., more_campaigns=True)`; tests use
    the single-campaign demo).

22. **Farmers as a CRM pipeline (17 Oct, same branch).** Who gets a harvest call is a rule now (`services.call_reason`,
    mirrored in `frontend/src/crm.js`): no harvest answer, an unsure answer, a harvest date that has passed, or marked to
    call (`to_call` is the planner's "always call"). Farmers with a firm, current answer are not called. Each farmer has
    a stage (To call, Calling, No answer, Answered, Offer, Deal, Delivered) shown as a board or a list on the Campaign
    page; the farmer page opens with the stage and next action and an activity timeline. The target chart shows each
    week's dates, links to the calendar (`/calendar?date=`), and a click on a part lists the farmers behind it. Deals
    carry `delivered_kg`. Not built yet: follow-up tasks with due dates, an owner per farmer.

Test note: `tests/test_audio_codec.py::test_decode_matches_stdlib_audioop_exactly` fails on
Python 3.13 because `audioop` was removed. Skip it when `audioop` is missing.
