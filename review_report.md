# Review Report

## Implemented in this pass

### Bug fixes
- Onboarding discovery now works with header-based credentials instead of failing FastAPI validation when the query token is omitted.
  - Backend: [backend/routers/onboard_router.py](/Users/larfan/Projects/sinch-pa/backend/routers/onboard_router.py:78), [backend/routers/onboard_router.py](/Users/larfan/Projects/sinch-pa/backend/routers/onboard_router.py:145), [backend/routers/onboard_router.py](/Users/larfan/Projects/sinch-pa/backend/routers/onboard_router.py:185)
  - Frontend: [frontend/src/pages/Setup.tsx](/Users/larfan/Projects/sinch-pa/frontend/src/pages/Setup.tsx:113)
- `QAService` is compatible again with providers and test doubles that do not accept the newer `timeout` or `question` kwargs.
  - [backend/services/ai/qa_service.py](/Users/larfan/Projects/sinch-pa/backend/services/ai/qa_service.py:288)
  - [backend/services/ai/qa_service.py](/Users/larfan/Projects/sinch-pa/backend/services/ai/qa_service.py:1087)
  - [backend/services/ai/qa_service.py](/Users/larfan/Projects/sinch-pa/backend/services/ai/qa_service.py:2420)
- Engineer detail no longer hard-fails the whole page after a transient sync error; the page keeps existing data and shows a recoverable banner instead.
  - [frontend/src/pages/EngineerDetail.tsx](/Users/larfan/Projects/sinch-pa/frontend/src/pages/EngineerDetail.tsx:79)
  - [frontend/src/pages/EngineerDetail.tsx](/Users/larfan/Projects/sinch-pa/frontend/src/pages/EngineerDetail.tsx:106)
  - [frontend/src/pages/EngineerDetail.tsx](/Users/larfan/Projects/sinch-pa/frontend/src/pages/EngineerDetail.tsx:137)
- Dashboard, Engineers, and Services now clear stale error/config state before reloading instead of keeping a previous failure pinned on screen.
  - [frontend/src/pages/Dashboard.tsx](/Users/larfan/Projects/sinch-pa/frontend/src/pages/Dashboard.tsx:83)
  - [frontend/src/pages/Engineers.tsx](/Users/larfan/Projects/sinch-pa/frontend/src/pages/Engineers.tsx:44)
  - [frontend/src/pages/Services.tsx](/Users/larfan/Projects/sinch-pa/frontend/src/pages/Services.tsx:120)

### Performance improvements
- Route-level lazy loading now splits the frontend by page instead of loading the whole application up front.
  - [frontend/src/App.tsx](/Users/larfan/Projects/sinch-pa/frontend/src/App.tsx:8)
  - Result: main entry bundle dropped from about `865.74 kB` to `287.42 kB` in production build output.
- DORA now fetches team metrics and velocity forecasts separately, so changing only the velocity history window no longer refetches all DORA data or blank the page behind a global spinner.
  - [frontend/src/pages/Dora.tsx](/Users/larfan/Projects/sinch-pa/frontend/src/pages/Dora.tsx:65)
  - [frontend/src/pages/Dora.tsx](/Users/larfan/Projects/sinch-pa/frontend/src/pages/Dora.tsx:74)
  - [frontend/src/pages/Dora.tsx](/Users/larfan/Projects/sinch-pa/frontend/src/pages/Dora.tsx:89)

## Features not implemented well enough

### Intelligence explainability
- The backend returns structured `evidence`, `entities`, `confidence`, and `debug` metadata, but the chat UI mostly renders only the final answer text.
  - API shape: [frontend/src/api/client.ts](/Users/larfan/Projects/sinch-pa/frontend/src/api/client.ts:174)
  - UI gap: [frontend/src/components/ChatPanel.tsx](/Users/larfan/Projects/sinch-pa/frontend/src/components/ChatPanel.tsx:75)
- Improvement: show evidence cards, source links, confidence, and one-click drill-down to the related team/engineer/epic/service. Right now the AI output is harder to trust than the data model allows.

### Sync observability
- The app has a scheduler, sync state, and alerting infrastructure, but the UI only exposes lightweight badges and fixed-delay refreshes.
  - Frontend usage: [frontend/src/components/SyncStatusBadge.tsx](/Users/larfan/Projects/sinch-pa/frontend/src/components/SyncStatusBadge.tsx)
  - Backend capabilities: [backend/services/scheduler.py](/Users/larfan/Projects/sinch-pa/backend/services/scheduler.py:147)
- Improvement: add per-job progress, last error details, queue state, and a dedicated sync history page. The current UX is acceptable for a demo, but thin for operations.

### Service catalog workflows
- Version enrichment is useful, but the user experience is still a blind fire-and-wait flow driven by long timeouts.
  - [frontend/src/pages/Services.tsx](/Users/larfan/Projects/sinch-pa/frontend/src/pages/Services.tsx:197)
  - [frontend/src/pages/Services.tsx](/Users/larfan/Projects/sinch-pa/frontend/src/pages/Services.tsx:204)
- Improvement: expose scan progress, last scan status, partial results, and direct links from services to related owners, repos, incidents, and DORA context.

## Features that should be built but are missing

### Alert center UI
- The backend already has alert services and notification plumbing, but there is no first-class frontend route for alerts, subscriptions, or alert triage.
  - Backend: [backend/routers/alerts_router.py](/Users/larfan/Projects/sinch-pa/backend/routers/alerts_router.py)
  - Missing in app routes/nav: [frontend/src/App.tsx](/Users/larfan/Projects/sinch-pa/frontend/src/App.tsx:44), [frontend/src/components/Layout.tsx](/Users/larfan/Projects/sinch-pa/frontend/src/components/Layout.tsx:6)

### Exportable executive reporting
- Directors will eventually need to export or schedule shareable summaries. There is no CSV/PDF/email digest flow in the frontend.
- Build: saved report presets, CSV export per page, and scheduled briefing delivery.

### Drill-through analytics
- The dashboard surfaces high-level metrics, but there is no consistent path from a warning/anomaly/prediction to the exact underlying records that produced it.
- Build: deep links from cards and badges into filtered MR lists, Jira issue sets, service ownership views, and explanation panels.

### Configuration and secrets UX
- Setup is functional, but there is no robust settings/admin area for rotating credentials, validating providers over time, or safely storing domain-specific secrets.
- Build: a dedicated settings page with secret rotation, validation history, and environment/config drift checks.

## Verification
- `uv run pytest backend/tests/test_qa_service.py`
- `npm --prefix frontend run build`
