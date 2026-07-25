# AgAI-33: Telephony-Integrated Dispatch Agent

**By Muhammad Umair | [Datawebify](https://datawebify.com)**

A production-grade AI agent that takes inbound calls through a self-hosted Asterisk/FreePBX system and dispatches jobs to field technicians based on skill, location, and urgency, rather than booking a single resource against a calendar. Built by porting the proven multi-agent pipeline from AgAI-7 (Voice and Chat Scheduling Agent) and closing the two capability gaps that pipeline didn't cover: self-hosted PBX call control and multi-technician workforce routing.

---

## Why This Project Exists

Most AI scheduling agents assume a managed telephony API (Twilio) and a single bookable resource (one calendar, one time slot). Real field-service businesses running self-hosted FreePBX and dispatching across a team of technicians need something structurally different: call control without a managed API in the loop, and job routing based on who's actually free, close by, and qualified for the work -- not just who has an open slot.

This project exists to close that specific capability gap and make it demonstrable: every file below is marked either **Ported from AgAI-7** (the proven 55-60% architectural overlap) or **New in AgAI-33** (the 40-45% built specifically for this gap).

---

## Business Outcomes

| Metric | Manual Dispatch | With AgAI-33 | Change |
|--------|-----------------|---------------|--------|
| Time to assign a technician | 5-15 minutes (phone tag, radio) | Under 30 seconds | 90%+ faster |
| After-hours call coverage | 0% | 100% | Full coverage |
| Technician matched by skill + proximity | Manual judgment call | Automatic, ranked | Consistent |
| Dispatcher hours spent triaging calls | 2-4 hours/day | Near zero | 90% reduction |
| Job-to-technician assignment errors | Wrong skill/too far (occasional) | Skill-gated, proximity-ranked | Reduced |

*(Business outcomes are portfolio-standard projections consistent with AgAI-7's model, to be replaced with real client metrics once deployed.)*

---

## Target Industries

- Field service companies running self-hosted PBX systems (HVAC, plumbing, electrical, security/alarm monitoring -- industries with legacy on-prem phone infrastructure)
- Dispatch-heavy operations: multi-technician teams, service-area routing, emergency/priority job handling
- Any business currently running FreePBX/Asterisk that wants AI call handling without migrating off self-hosted telephony

---

## System Architecture

```
Inbound Call (Asterisk ARI)          Inbound Text (Twilio SMS/WhatsApp)
        |                                       |
   ARI Client + Voice Bridge              Chat Normalizer
   (answer, STT via ElevenLabs)                 |
        |                                       |
        └───────────────┬───────────────────────┘
                         |
                  Intent Parser Agent  (Gemini 2.5 Flash)
                         |
              ┌──────────┴──────────┐
              |                     |
      Dispatch Request      Check Status / Cancel
              |                     |
      Dispatch Agent          Job Status Agent
   (skill + proximity +
      queue ranking)
              |
      Conflict Resolver
    (top-3 alternatives if
       no clear best fit)
              |
    Dispatch Confirmation Agent
              |
      Supabase + Notifications
   (SendGrid email + Twilio SMS
    to customer AND technician)
```

### Agent Responsibilities

| Agent | Status | Responsibility |
|---|---|---|
| Intent Parser | **Ported**, prompt rewritten | Classifies dispatch_request / check_status / cancel / general_inquiry and extracts service type, location, urgency (replaces date/time extraction) |
| Dispatch Agent | **New** | Queries technician registry by skill, filters by availability, ranks by proximity (Google Geocoding) and queue depth |
| Conflict Resolver | **Ported**, domain swapped | Offers top-3 alternative technicians when there's no single clear best match |
| Dispatch Confirmation Agent | **Ported**, domain swapped | Writes the dispatch record, notifies customer (email) and technician (SMS) |
| Job Status Agent | **Ported**, domain swapped | Looks up and cancels dispatch jobs by phone number |
| ARI Client | **New** | Asterisk REST Interface wrapper: call answer, hangup, bridging, external media |
| Voice Bridge | **New** | STT/TTS bridge between raw Asterisk audio and the text-based agent pipeline |

---

## Ported from AgAI-7 vs. New in AgAI-33

**Ported (55-60%), architecture unchanged, domain logic adapted:**
- LangGraph orchestration shape (node functions, conditional routing, single-responsibility agents)
- Session state management across conversation turns (Supabase-backed)
- Conflict resolution pattern (offer alternatives when no clean single match)
- Defensive error handling (every external call wrapped, pipeline never crashes on a downstream failure)
- Chat/SMS/WhatsApp channel handling via Twilio (unchanged -- only voice moved to Asterisk)
- Email/SMS notification pattern

**New in AgAI-33 (the 40-45% gap):**
- **FreePBX/Asterisk integration (~15%)** -- `core/ari_client.py`, `api/ari_router.py`, `notifications/voice_bridge.py`. Asterisk ARI event stream (WebSocket), call control (answer/hangup/bridge), and a from-scratch STT/TTS bridge, since Asterisk (unlike Twilio) hands you raw audio, not a finished transcript.
- **Field technician dispatch logic (~20%)** -- `agents/dispatch_agent.py`, extended Supabase schema (`dispatch_technicians`, `dispatch_technician_locations`). Skill matching, proximity ranking via Google Geocoding, queue-depth-aware scoring.
- **Adapter pattern for existing AI engines (~5-10%)** -- `api/dispatch_router.py`'s `/dispatch/webhook/web` endpoint accepts a plain JSON message/session_id contract, so a client's existing dashboard or AI engine can call directly into the dispatch pipeline without going through a phone call at all.

---

## Tech Stack

| Layer | Technology | Status |
|-------|-----------|--------|
| Agent Framework | LangGraph | Ported |
| AI Model | Gemini 2.5 Flash | Ported |
| Telephony | Asterisk ARI (self-hosted) | **New** |
| PBX | FreePBX | **New** |
| Voice STT/TTS | ElevenLabs | **New** (bridge), reuses existing API key |
| Geocoding | Google Geocoding API | **New**, reuses existing API key |
| Chat/SMS | Twilio (SMS/WhatsApp only) | Ported |
| Backend API | FastAPI + Uvicorn | Ported |
| Database | Supabase (PostgreSQL) | Ported infra, new schema |
| Notifications | SendGrid + Twilio SMS | Ported |
| Deployment | Docker + Railway | Ported |
| Language | Python 3.12 | Ported |

---

## Supabase Schema

All columns are prefixed `dispatch_` to match the planned frontend at `dispatch.datawebify.com` (backend API deployed separately at `dispatch-api.datawebify.com`). Python code keeps clean, unprefixed field names internally; `core/database.py` translates at the database boundary only (see `_DISPATCH_JOB_COLUMNS`, `_TECHNICIAN_COLUMNS`, `_SESSION_COLUMNS` mapping dicts).

- **dispatch_technicians** -- registry: skills array, status, current location, queue depth, shift hours
- **dispatch_technician_locations** -- location ping history, for future live-tracking
- **dispatch_jobs** -- every dispatch request with assigned technician, status, urgency
- **dispatch_sessions** -- conversation state, same role as AgAI-7's sessions table
- **dispatch_agent_logs** -- full audit trail of every agent event

Schema file: `supabase/schema.sql`. Includes 3 seed technicians for local testing.

---

## Project Structure

```
AgAI_33_FreePBX_Dispatch_Agent/
├── agents/
│   ├── intent_parser.py               # Ported, prompt rewritten for dispatch
│   ├── dispatch_agent.py              # NEW -- skill/proximity/queue ranking
│   ├── conflict_resolver.py           # Ported, domain swapped
│   ├── dispatch_confirmation_agent.py # Ported, domain swapped
│   └── job_status_agent.py            # Ported, domain swapped
├── core/
│   ├── config.py                      # Ported + Asterisk/dispatch settings
│   ├── database.py                    # Ported pattern, dispatch_ column mapping
│   ├── models.py                      # Ported shape, dispatch domain types
│   ├── normalizer.py                  # Ported + normalize_asterisk_event()
│   ├── session_manager.py             # Ported unchanged
│   ├── logger.py                      # Ported unchanged
│   ├── orchestrator.py                # Ported graph shape, dispatch nodes
│   └── ari_client.py                  # NEW -- Asterisk ARI REST + WebSocket client
├── api/
│   ├── main.py                        # Ported + ARI listener startup task
│   ├── dispatch_router.py             # Ported (was chat_router.py)
│   ├── ari_router.py                  # NEW -- ARI call lifecycle handling
│   └── metrics_router.py              # Ported pattern, dispatch KPIs
├── notifications/
│   ├── email_sender.py                # Ported, dispatch copy
│   ├── sms_sender.py                  # Ported + technician notification (new)
│   └── voice_bridge.py                # NEW -- STT/TTS for Asterisk calls
├── supabase/
│   └── schema.sql                     # NEW -- dispatch_ prefixed schema
├── docker/
│   ├── docker-compose.yml             # NEW -- local FreePBX dev environment
│   └── extensions_custom.conf         # NEW -- Stasis app dialplan
├── dispatch-frontend/                 # NEW -- dispatch.datawebify.com dashboard
│   ├── index.html                     # Single-page shell
│   ├── css/                           # Tokens, layout, components
│   ├── js/                            # Roster, board, timeline, simulator, API client
│   ├── package.json                   # Railway static-serve config
│   └── README.md                      # Local run + deployment instructions
├── tests/
│   └── test_dispatch_agent.py         # NEW -- ranking logic, verified passing
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

---

## Local Setup

### Prerequisites
- Python 3.12
- Docker Desktop (for local FreePBX dev environment)
- A Supabase project with the schema in `supabase/schema.sql` applied
- Google Gemini, Google Geocoding, ElevenLabs, SendGrid, Twilio, and Supabase API keys

### 1. Install dependencies

```bash
python -m venv venv
venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Fill in your credentials. `GOOGLE_API_KEY` and `ELEVENLABS_API_KEY` can reuse existing keys from other projects in this portfolio.

### 3. Apply the Supabase schema

Run `supabase/schema.sql` in your Supabase project's SQL Editor. Creates all tables, indexes, and 3 seed technicians.

### 4. Run the ranking tests (no PBX or live API keys required)

```bash
pytest tests/test_dispatch_agent.py -v
```

### 5. Bring up the local Asterisk dev environment

```bash
cd docker
docker compose up -d
```

Asterisk ARI: `http://localhost:8088/ari` | SIP: `localhost:5060`

Note: ARI (TCP) is confirmed working end to end against this environment. SIP registration over UDP (e.g. from a softphone like MicroSIP) was found to be blocked by Docker Desktop's WSL2 network backend on Windows during development -- Asterisk's PJSIP transport and Docker's port-forwarding are both independently confirmed correct, but UDP packets do not reliably cross the Windows/WSL2 boundary in this environment. See README "Honest Status Notes" for the full diagnostic trail. This does not block ARI-based development or testing; it specifically affects placing a live test call locally on Windows.

### 6. Run the API

```bash
uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

---

## Honest Status Notes (What's Verified vs. Not Yet)

This project is built to the same "not a demo" standard as the rest of the portfolio, which means being explicit about what has and hasn't been validated end to end, rather than presenting everything as equally proven.

**Verified:**
- Dispatch ranking logic (skill filter, proximity scoring, queue-depth weighting, graceful degradation when geocoding is unavailable) -- unit tested, all tests passing against the actual source file.
- Full LangGraph pipeline shape (intent parse -> dispatch match -> conflict resolution or confirmation -> job lookup/cancel) -- structurally identical to AgAI-7's proven graph, same node/routing pattern.
- Supabase schema and `dispatch_` column mapping -- schema applied and confirmed live in the project's Supabase instance.
- **Asterisk ARI connectivity end to end** -- `core/ari_client.py` connects to a real Asterisk instance's ARI WebSocket, authenticates, and registers the `agai33_dispatch` Stasis app successfully (confirmed live: `Creating Stasis app 'agai33_dispatch'` in Asterisk's own log, and `ari_client.connected` in the API's log). The FastAPI app starts cleanly, all three routers (`dispatch`, `ari`, `metrics`) load, and `/health` and `/ari/health` both return healthy against the running local stack.
- Asterisk's PJSIP transport and Docker's port-forwarding layer are both independently confirmed correct: `pjsip show transports` shows `transport-udp` bound to `0.0.0.0:5060` inside the container, and `docker port` confirms Docker is forwarding host port 5060/udp into it. Both sides of the container boundary are configured correctly.

**Attempted but blocked by local environment, not by AgAI-33's code** (this is the honest, specific finding, not a vague caveat):
- A SIP softphone (MicroSIP) registered against the local Asterisk container consistently failed to reach it over UDP, despite: (a) `pjsip.conf`'s endpoint configuration confirmed correct via `pjsip show endpoints`, (b) explicit Windows Firewall inbound-allow rules added for UDP 5060 and the RTP range, and (c) `pjsip set logger on` showing zero SIP traffic reaching Asterisk during repeated registration attempts, while the same container's TCP-based ARI connection (port 8088) worked perfectly throughout. This pattern -- TCP forwarding works, UDP forwarding silently drops -- is a known category of issue with Docker Desktop's WSL2 network backend on Windows, not a defect in `pjsip.conf`, `docker-compose.yml`, or `core/ari_client.py`. Diagnosed down to "packets never leave the Windows/WSL2 boundary"; further isolation would require changing Docker Desktop's network backend (e.g. Hyper-V mode) or testing on a different host OS, which is outside the scope of validating this project's code.
- Practical implication: local SIP call testing on this Windows machine is blocked by environment networking, not by anything in this repository. The real, decisive validation point was always going to be a live client PBX (SIP trunk topology, network path, and FreePBX configuration all vary per deployment and can't be fully simulated locally regardless of OS) -- this local environment served its purpose by proving ARI connectivity and catching this UDP-forwarding limitation early, before it could surface during an actual client engagement.
- Answering an actual inbound call, bridging it to external media, and receiving RTP audio therefore remains unvalidated locally. RTP/externalMedia audio buffering and silence detection (`notifications/voice_bridge.py`) -- the chunk-buffering and silence-timer logic is unit-testable independent of a live PBX, but real-world RMS thresholds and any externalMedia framing details still need calibration against actual phone-line audio from a placed call, once a working call path exists (either via a Docker networking fix or a real client PBX).

**Docker image decision (corrected once already):** The first local dev environment pointed at `tiredofit/freepbx`, which turned out not to exist on Docker Hub at all (`pull access denied`). Rather than guess again, every FreePBX-wrapper image on Docker Hub was checked and all were stale (2016-2021, several with EOL Asterisk/Ubuntu versions). The environment now runs a plain, actively maintained Asterisk image (`andrius/asterisk`, updated daily, 120 stars, 800K+ pulls) with ARI enabled directly via `docker/asterisk-conf/`, rather than a FreePBX GUI wrapper -- confirmed booting cleanly and passing ARI connectivity end to end.

**Explicitly deferred, not hidden:**
- Technician phone number is correctly threaded through to the SMS layer (`assigned_technician_phone` on `DispatchRecord`), but the geocoding call depends on a live `GOOGLE_API_KEY` with the Geocoding API enabled on the Google Cloud project -- confirm this is enabled before relying on proximity ranking in a real call.

---

## Integration Pattern: Plugging Into an Existing AI Engine

Unlike AgAI-7, which owns its full architecture end to end, this project also demonstrates the adapter shape needed when a client already has an AI engine or dashboard and wants dispatch logic added to it rather than replaced:

`POST /dispatch/webhook/web` accepts:
```json
{
  "message": "Customer's request text",
  "session_id": "optional-existing-session-id",
  "customer_phone": "+1234567890",
  "customer_email": "customer@example.com",
  "customer_name": "John Smith"
}
```

and returns:
```json
{
  "reply": "Your HVAC job has been dispatched to Carlos Mendes...",
  "session_id": "...",
  "channel": "chat",
  "dispatch": { "job_id": "...", "assigned_technician_name": "...", "status": "assigned" }
}
```

A client's existing engine calls this endpoint directly -- the dispatch logic, technician ranking, and notification pipeline run identically whether the request arrived via a phone call, SMS, or a client's own dashboard.

---

## Frontend Dashboard

A live dashboard for `dispatch.datawebify.com` ships in `dispatch-frontend/`
(plain HTML/CSS/ES modules, no build step). It gives a non-technical
evaluator something to *see* rather than raw JSON:

- **Live dispatch board** -- active jobs by status, polling `GET /dispatch/jobs` every 8 seconds
- **Technician roster view** -- status, skills, queue depth per technician, from `GET /dispatch/technicians`, so a viewer can see *why* a given technician was matched to a job
- **Dispatch timeline** -- click any job to see its lifecycle (intent parsed -> assigned -> en route -> in progress -> completed), reconstructed client-side from the job record
- **"Simulate a call" widget** -- a docked panel that lets anyone type a request ("AC is out, 123 Main St, it's urgent") and hit `POST /dispatch/webhook/web` directly, watching the same pipeline a real phone call would trigger, no SIP setup required

Styled to match the Datawebify brand (indigo/violet, matching `style.css` on the main portfolio site) rather than a generic admin template. See `dispatch-frontend/README.md` for local run and deployment instructions.

**Verified working end to end**: tested against a live local backend and Supabase instance -- skill-based technician matching visibly picks the correct technician per job type (e.g. a plumbing request routes to a plumbing-skilled technician, not just whoever's free), roster and board update live after a dispatch, and the full loop (intent parse -> match -> confirm -> notify -> board refresh) completes with no errors.

---

## Portfolio

This is Project 33 of 50 in the Datawebify Agentic AI portfolio. Built to close the capability gap identified in the FreePBX/dispatch job-post pattern seen on Upwork.

---

## Contact

**Muhammad Umair**
Agentic AI Specialist and Enterprise Consultant
[datawebify.com](https://datawebify.com) | [github.com/umair801](https://github.com/umair801)
