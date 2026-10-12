# Harvest-Call planner app (React)

Vite + React single-page app for the planner pages (task C-04):

| Route | Page |
|---|---|
| `/` | Live forecast |
| `/setup` | Setup (3 steps) |
| `/approvals` | Approvals |
| `/users` | Users and roles (only for someone with the `users.admin` right) |
| `/login` | Demo sign-in: pick a person |

Moving between pages does not reload: the live data connection (`/api/stream`) opens once and
is shared. Each page is its own chunk, loaded the first time it is opened. The old addresses
(`index.html`, `setup.html`, `approvals.html`, `users.html`, `login.html`, with their `?next=`) redirect to
the routes, so the call client's links and old bookmarks still work.

## Layout

```
src/
  App.jsx          routes, old-URL redirects, lazy pages
  live.jsx         one shared live-state connection (useLive)
  toast.jsx        Sonner toasts and useAct (watch-only guard, 401 back to sign-in, Undo on the toast)
  Shell.jsx        sidebar / phone tab bar, top bar, banners
  ui.jsx           Icon, Avatar, Pill, Dialog (Radix)
  react.css        styles for the toasts, dialogs and chart tooltip
  lib.js           re-exports from web/js/data.js, the page list
  pages/           Forecast, Setup, Approvals, Users, Login
  components/      the pieces of each page (forecast/, setup/, approvals/)
```

Libraries, kept unstyled so the app keeps its own look:
- **Sonner**: toasts. Approve and Reject put an "Undo" button on the toast.
- **Motion**: calm transitions (offers slide when re-sorted, the gap card and the on-track card fade
  into each other, each page fades in). `MotionConfig reducedMotion="user"` turns them off for
  people who ask their device for less motion.
- **Radix UI**: the dialogs (focus kept inside, Esc to close) and the chart's week tooltip (stays
  on screen near the edges; hover, keyboard focus or a tap opens it).

What is shared with `web/` (not copied):
- `web/css/app.css`: the design tokens and all styles.
- `web/js/data.js`: the API, demo sign-in, live stream and formatting.

The call client (`call.html`, task B-03) and `mic-test.html` stay vanilla JS in `web/`. `npm run build`
copies them into `dist/` with `config.js`, the favicon and `farmers-template.csv`, so one folder serves
every page.

## Run locally

Start the backend first (port 8000), then:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The dev server proxies `/api`, `/ws`, `/config.js` and the call client
to the backend. To use another backend, set `HARVEST_BACKEND=http://localhost:8001`.

## Build

```bash
npm run build
```

The output goes to `frontend/dist/`. `npm run preview` serves it at http://localhost:4173.

## Deploy

Firebase Hosting serves `frontend/dist`. `deploy/deploy.sh` writes `web/config.js`, then runs
`npm ci && npm run build` here (the build copies that `config.js` and the call client), then
`firebase deploy`. `firebase.json` has the single-page rewrite, so `/setup` and the old `.html`
addresses load the app, while real files such as `call.html` are served first.

To go back to the vanilla pages, set `"public": "web"` in `firebase.json` and drop the rewrite.

The backend's own static serving (`STATIC_DIR`) has no single-page rewrite, so it only suits `web/`.
