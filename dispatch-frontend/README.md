# Dispatch Console — Frontend

Static, no-build frontend for the AgAI-33 dispatch dashboard. Plain HTML/CSS/JS
(ES modules), deploys as-is to any static host. No npm, no bundler.

## Local testing against your local backend

1. Start the backend as usual:
   ```
   uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
   ```
2. Serve this folder with any static server, e.g.:
   ```
   python -m http.server 5500
   ```
3. Open `http://localhost:5500` in a browser. The frontend auto-detects
   `localhost`/`127.0.0.1` and points at `http://127.0.0.1:8000`.

No CORS proxy needed — the backend's `CORSMiddleware` already allows `*`.

## Pointing at a different backend (demo flexibility)

Append `?api=https://your-backend-url` to the URL to override the API base
without touching code — useful for demoing against a client's staging
backend or a Railway preview URL.

## Deployment (Railway → dispatch.datawebify.com)

This is a static site with a `package.json` that runs it via `serve`, so
Railway auto-detects it as a Node service:

1. In Railway, create a **new service** in the same project as the backend
   (or a separate project, either works), **Deploy from GitHub repo**,
   same repo as the backend.
2. In that service's **Settings → Source**, set **Root Directory** to
   `dispatch-frontend`. This tells Railway to build/run only this
   subfolder, ignoring the Python backend beside it.
3. Railway detects `package.json`, runs `npm install` then `npm start`
   (`serve -s . -l $PORT`), no further config needed.
4. Once deployed, add a custom domain in **Settings → Networking**:
   `dispatch.datawebify.com`, then add the CNAME Railway gives you to your
   DNS provider.
5. Visit `https://dispatch.datawebify.com` — it will auto-detect it's not
   on `localhost` and point at `https://dispatch-api.datawebify.com` (see
   `js/api.js`, `resolveApiBase()`). Update that fallback URL if the
   production API domain ever changes.

Alternatively this deploys identically to Netlify, Vercel, or any static
host — the `package.json`/`serve` setup is only needed for Railway's
auto-detection; other static hosts serve `index.html` directly with no
build step at all.

## File map

```
index.html          Single-page shell: status bar, roster, board, timeline, simulator
css/tokens.css       Design tokens (color, type, spacing)
css/layout.css       Grid/shell layout
css/components.css   All component styling
js/api.js            Fetch wrapper for all 4 backend endpoints
js/helpers.js         Shared formatting/status utilities
js/roster.js          Technician roster panel
js/board.js           Job board panel + status filter chips
js/timeline.js        Job lifecycle timeline (derived client-side from job fields)
js/metrics.js         Header KPI strip (GET /metrics)
js/simulator.js        "Simulate a call" docked widget (POST /dispatch/webhook/web)
js/main.js             Entry point: wiring + poll loop (8s interval)
```

## Notes for future work

- **Timeline data**: there's no dedicated `/dispatch/jobs/{id}/events` endpoint
  yet, so the timeline is reconstructed client-side from the job's `status`
  field against a fixed lifecycle order (`pending → assigned → en_route →
  in_progress → completed`). This is accurate for the current schema but
  won't show exact per-stage timestamps until the backend logs those events
  explicitly (`dispatch_agent_logs` table already exists for this — a future
  endpoint could expose it per job).
- **Polling, not websockets**: refreshes every 8 seconds via `setInterval`.
  Fine for a demo/portfolio piece at this job volume; swap for a websocket
  or SSE stream if this becomes a real multi-dispatcher production tool.
- **No auth**: matches the backend's current no-auth state. Add a token
  header in `js/api.js`'s `request()` function if/when the backend adds auth.
