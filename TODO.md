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

2. **Confirmation call can be marked confirmed when the farmer wanted changes.**
   `services.finish_call` sets `confirmed_by_voice=True` for any clean ending that is not
   `declined` or `stopped` (so `escalated` and `wrong_person` count too). Fix: require an
   explicit outcome for confirm calls.

3. **"Agent never sees the limits" is not strictly true.** `check_offer` returns the ceiling on
   `escalate` and the floor on a below-floor counter. Either fix the README and the `tools.py`
   docstring, or stop returning the number.

4. **Read-back before saving is a prompt rule only.** `record_harvest` saves if the model sends
   `confirmed_by_farmer=true` without the unconfirmed call first. Fix: track the read-back in
   `CallSession` and refuse otherwise.

5. **Counters inside the limits are accepted immediately** (no ladder, even at the ceiling).
   Confirm that is intended and say so in the README.

6. **Docs:** AI disclosure and "read the reference price first" are prompt-only.

Test note: `tests/test_audio_codec.py::test_decode_matches_stdlib_audioop_exactly` fails on
Python 3.13 because `audioop` was removed. Skip it when `audioop` is missing.
