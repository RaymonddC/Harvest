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
    - Prompt problems seen in the recordings (not fixed): in 2 of 6 calls the farmer's "naik jadi 3300" was taken
      as a harvest weight and `record_harvest` was called with 3,300 kg; the agent sometimes says the reference price in
      English; it often repeats the consent question; it does not always call `end_call` (the last farmer line, "Tidak ada,
      terima kasih", exists to let it finish).

Test note: `tests/test_audio_codec.py::test_decode_matches_stdlib_audioop_exactly` fails on
Python 3.13 because `audioop` was removed. Skip it when `audioop` is missing.
