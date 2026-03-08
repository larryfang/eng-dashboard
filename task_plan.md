# Task Plan: Onboarding Audit and Revamp

## Goal
Map the existing onboarding flow for new teams/domains, fix weak points, and deliver a smoother end-to-end onboarding experience in the app.

## Phases
- [x] Phase 1: Plan and setup
- [x] Phase 2: Research current onboarding flow and failure points
- [x] Phase 3: Implement onboarding improvements or revamp
- [x] Phase 4: Review, verify, and deliver

## Key Questions
1. What frontend routes/pages currently handle onboarding and setup?
2. What backend endpoints and persistence steps support onboarding?
3. Where does the current flow break, confuse users, or require too much manual work?
4. What is the smallest set of changes that makes onboarding feel reliable and seamless?

## Decisions Made
- Audit frontend and backend onboarding before changing UX.
- Consolidate to a single canonical onboarding component.
- Persist domain credentials separately from `/api/config` to avoid leaking secrets.
- Make runtime sync/validation prefer active-domain credentials captured during onboarding.

## Errors Encountered
- Initial multi-file backend patch failed on a stale context block in `gitlab_collector.py`; reapplied in smaller chunks.

## Status
**Completed** - Canonical onboarding flow shipped, runtime credential loading fixed, and focused tests/build passed.
