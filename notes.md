# Onboarding Notes

## Scope
Audit and improve onboarding for adding new teams or new systems/domains in the app.

## Findings
- The app currently has two onboarding implementations: `frontend/src/pages/Setup.tsx` and `frontend/src/pages/Setup/index.tsx` plus step files. The routed import path `./pages/Setup` is ambiguous, creating drift risk.
- The monolithic `Setup.tsx` is the only flow that appears structurally compatible with `POST /api/onboard/create`; the step-based flow builds a different payload shape and would fail if it were the active route.
- `POST /api/onboard/create` persists org/team config and seeds the domain DB, but it does not persist GitLab/Jira credentials needed by runtime sync services.
- Runtime sync and validation paths mostly read credentials from environment variables (`GITLAB_TOKEN`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, `JIRA_URL`, `PORT_CLIENT_ID`, `PORT_CLIENT_SECRET`) rather than domain-specific onboarding data.
- This means onboarding can look successful while the new domain still cannot sync data unless machine-level env vars happen to be present.
- Current onboarding also spreads key tasks across too many steps, hides discovery power, and gives weak post-create progress visibility.
- Returning raw integration configs through `/api/config` would leak secrets if onboarding started storing credentials there directly, so secret persistence needs a separate path.

## Decisions
- Consolidate to one canonical onboarding entry component.
- Store domain credentials outside the public config response in a domain-scoped secrets file.
- Update runtime services and config validation to prefer active-domain secrets over global env vars.
- Replace the current fragmented setup UX with a smaller, clearer wizard focused on basics, connections, discovery, review, and sync progress.

## Implemented
- Added `backend/services/domain_credentials.py` to persist and load per-domain GitLab, Jira, Port, and Snyk credentials from `data/domains/{slug}.secrets.json`.
- Updated onboarding validate/discovery endpoints to support custom GitLab URLs, use inherited GitLab membership discovery (`/members/all`), and fail loudly instead of silently truncating discovery.
- Hardened `POST /api/onboard/create` so it stores safe public config separately from runtime secrets and requires GitLab credentials for a usable domain.
- Switched runtime validation/sync services to active-domain credentials for GitLab, Jira, Port, repo scanning, version scanning, and related GitLab routes.
- Fixed legacy active-domain drift by making `get_config()` resolve the active domain config and resetting GitLab team caches on domain switch.
- Replaced the duplicated onboarding UIs with one canonical setup wizard in `frontend/src/pages/Setup.tsx`, and turned `frontend/src/pages/Setup/index.tsx` into a thin re-export.
- New setup UX now includes:
  - basics step for domain identity
  - connection step with GitLab/Jira validation plus optional Port/Snyk
  - GitLab team discovery from base group
  - Jira project discovery
  - inherited member discovery per team or in bulk
  - review step with readiness warnings
  - real sync progress cards backed by `/api/sync/schedule`
- Added onboarding-focused backend tests covering custom GitLab URLs, inherited member discovery, and active-domain config/cache behavior.

## Verification
- `uv run pytest backend/tests/test_onboarding_runtime.py backend/tests/test_config_router.py backend/tests/test_activity_and_datetime_services.py` -> `9 passed`
- `npm --prefix frontend run build` -> success
