# Harvest-Call design system

How the dashboard should look and feel. Read this before building or changing a screen. The tokens live in
`frontend/src/react.css` (the "Design system pass" block on `body.app`) on top of `web/css/app.css`. The structure was
shaped with two public DESIGN.md analyses as references (a café brand's green roles and warm canvas, a finance
site's data tables); the palette, type and content are Harvest-Call's own.

## 1. Visual theme and atmosphere

A working tool for a palm-oil mill's planner, used at a desk through the day. Calm, warm and plain: a deep forest
sidebar, a warm off-white page, white cards that sit on a whisper of shadow, and numbers in sentences. Green means
"ours and fine", amber means "needs you", red means "wrong". The farmers are people, so they are drawn (portraits),
not initials. Density is high inside a card and generous between cards.

## 2. Colour palette and roles

| Name | Hex | Role |
|---|---|---|
| Deep green | `#0F3D2A` | Sidebar, dark bands, the main dark button (`.btn.solid`) |
| Action green | `#16774E` | Filled actions (`.btn.leaf`), links, switches, progress bars, "answered" |
| Text green | `#12573A` | Green words: active tab, positive figures, mint pill text |
| Green wash | `#E4F1E9` | Selected and soft states, mint pills, focus halo |
| Bright mint | `#2FBF7F` | The one call to action on a dark band (`.btn.mint`) only |
| Warm canvas | `#F3F2EC` | The page behind the cards |
| Surface | `#FFFFFF` | Cards, sheets, inputs |
| Text | `#1B231F` | Body text (never pure black) |
| Muted | `#5B6660` | Labels, secondary lines, table headers |
| Hairline | `#E5E4DD` | Table row rules, dividers inside a card |
| Amber | `#E3A72F` (text `#8A5605`) | Needs attention: to call, short weeks, waiting offers, unpaid |
| Red | `#C2410C` (text `#8A2E0D`) | Over capacity, complaints, churn signals, errors |
| Blue | `#3C8FD0` | Waiting for approval (in the supply bars) only |

Stage colours (board, overview strip, chips): to call amber, calling blue, no answer red-orange, answered action
green, offer brown `#8A5605`, deal deep green, delivered grey `#6B7280`.

## 3. Typography

One family: **Plus Jakarta Sans** (400 to 800). No serif and no monospace.

| Use | Size | Weight |
|---|---|---|
| Page title | 28px | 800, tracking -0.02em |
| Card title | 17 to 18px | 700 |
| Headline figure in a sentence | 26px | 800 |
| Figure in a ledger or column | 19 to 26px | 800 |
| Body | 14 to 14.5px | 400 to 500 |
| Label, table header | 12.5px | 700, muted |
| Small print | 12 to 12.5px | 400, muted |

Numbers use tabular figures (`.num`). Sentence case everywhere; no all-caps labels, no eyebrow labels above titles.

## 4. Components

- **Buttons**: pill (`999px`), 44px tall (`.sm` smaller), press in to `scale(.96)`, no glow underneath.
  `.btn.solid` deep green for the page's main action; `.btn.leaf` action green for a positive action in context; plain
  white with a `#CFCEC5` border for secondary; `.ghost` text-only. Labels say what happens ("Call them", "Fill it",
  "Record delivery"), never "Go" or "Submit".
- **Cards**: white, 12px radius, no border, shadow `0 0 .5px rgba(16,24,20,.16), 0 1px 2px rgba(16,24,20,.10)`.
- **Sheets and dialogs**: a lifted shadow (three soft layers), never a heavy single drop.
- **Tables**: rows split by one hairline, no vertical rules, no header fill; header muted 12.5px; hover row `#FAFAF6`;
  short values do not wrap.
- **Switch** (Agent calls): 34 by 20px track, action green when on.
- **Pills and chips**: soft wash background with dark text of the same hue.
- **Portraits** (`FarmerFace`): every person gets a drawn face; organisations (suppliers) keep initials on ink.
- **Notices**: a plain line on the page (headline sentence, muted explanation, action on the right), not a tinted
  box with a coloured stripe.

## 5. Layout

8px grid. Page gutter 32px desktop, 16px phone. Cards stack with 18px between them; content inside a card uses 10 to
16px gaps. Parts of a whole sit in one bar with a plain ledger (columns split by hairlines) under it, not as a row of
identical tiles. Lists are rows with dividers, not stacks of boxes.

## 6. Depth and elevation

Three levels only: flat (page, table rows), card (whisper shadow), lifted (sheets, dialogs, menus). No gradients on
surfaces or bars; colour blocks carry depth (the dark sidebar against the warm page).

## 7. Do's and don'ts

Do:
- Put the number in a sentence ("454 t of the 500 t target is in hand").
- Give green one job per tier (deep for chrome, action for doing, text for meaning, wash for states).
- Keep amber for "needs you" and red for "wrong"; never as decoration.
- Write labels and buttons in the planner's words.

Don't:
- No identical stat tiles, no coloured left stripes on boxes, no gradient fills, no all-caps eyebrows.
- No middle-dot strings as decoration, no arrows appended to buttons.
- No pure black text, no pure white page.
- No visible scrollbars (content still scrolls).

## 8. Responsive behaviour

- At 860px and below the sidebar becomes a bottom bar; ledgers and stage columns drop to two or three per row.
- Tables scroll sideways inside their card, never the page.
- Touch targets are at least 44px.
- The 3D phone on sign-in shows only above 860px wide and 480px tall.

## 9. Agent prompt guide

"Build it in Harvest-Call's system: warm canvas `#F3F2EC`, white 12px cards with a whisper shadow, Plus Jakarta Sans,
deep green `#0F3D2A` for the main button and chrome, action green `#16774E` for positive actions and links, amber for
what needs the planner, numbers in sentences, rows with hairlines, pill buttons with plain verbs, drawn portraits for
people."
