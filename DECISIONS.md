# Decisions (task C-03)

| Question | Decision | Status |
|---|---|---|
| Browser call or real number? | Browser call (`web/call.html`). A telephony bridge is the VA-8 stretch goal. | Decided |
| Crop | Palm fresh fruit bunches (FFB), Riau, Indonesia, per the design canvas | Default, change with `DEMO_CROP` |
| Language | Bahasa Indonesia (`DEMO_LANGUAGE`), with English caption lines (`CAPTION_TRANSLATE_TO`) | Confirm with the C-02 speech test |
| Prices | Floor Rp 2,900, reference 3,100, ceiling 3,350 per kg; first offer +4% (Rp 3,220), then steps of 2%. A counter inside the limits is accepted; above the ceiling goes to the planner | Illustrative; replace the reference with a published provincial FFB price |
| Target | 100 t per week; a week is a gap below 80 t (`GAP_TOLERANCE=0.2`) | Matches the wireframe |
| Buyer | "Koperasi Sawit Maju" (fictional), planner "Dewi" | `MILL_NAME`, `PLANNER_NAME` |
| Live model | `gemini-2.5-flash-native-audio-preview-09-2025` | Check it is still current before recording; set `LIVE_MODEL` |
| Dashboard auth | Optional shared `PLANNER_TOKEN`; Firestore reads are public because the data is synthetic | Fine for the demo; add Firebase Auth before any real data |

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
