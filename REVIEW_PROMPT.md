# Claude Code Review Prompt — sinch-pa Intelligence Layer

Copy the prompt below into Claude Code. It is tailored to your exact codebase structure, file paths, and known patterns.

---

## The Prompt

```
ultrathink

You are reviewing the sinch-pa Engineering Director Dashboard — specifically its AI "Ask Intelligence" feature and overall backend health. The project is React + FastAPI with SQLite. Read CLAUDE.md first for project rules.

## Phase 1: Bug Audit (scan for correctness issues)

Review these files for bugs, race conditions, and data-correctness problems:

1. **`backend/routers/ai_router.py`** — The `/api/ai/ask` endpoint and the briefing/anomaly/prediction endpoints. Check:
   - The imports use bare `from services.ai.…` (line 23, 30, 38, 50, 67, 84) instead of `from backend.services.ai.…`. CLAUDE.md explicitly says bare imports are forbidden and cause dual module identity. Verify whether this is actually broken at runtime or just a latent bug.
   - All service classes are instantiated fresh per request (`QAService()`, `BriefingService()`, etc). Check if this causes metadata cache thrashing since `QAService` uses a class-level `_metadata_cache` with a `Lock()` — does a new instance share the class-level cache or not?
   - Thread safety: FastAPI uses async endpoints but QAService does synchronous DB calls with `create_ecosystem_session()`. Are there potential deadlocks or event-loop blocking?

2. **`backend/services/ai/qa_service.py`** (2,712 lines) — The core Q&A engine. Audit:
   - **Intent classification**: The keyword-based fallback uses simple substring matching. Find cases where the wrong intent would be selected (e.g., "who is working on services" might match both `roster` and `services`). How robust is the tie-breaking via `_INTENT_PRIORITY`?
   - **Entity resolution**: Check how team names are resolved from user input. Does fuzzy matching (`_fuzzy_match` with edit distance ≤ 2) cause false positives? E.g., "AI" team matching random words?
   - **Evidence fetching**: Look for N+1 query patterns, missing `.filter()` for timeframe scoping, or cases where empty data returns a misleading "no results" instead of "no data for this period".
   - **LLM prompt construction**: Check token budget enforcement (`AI_PROMPT_TOKEN_BUDGET=2600`). Is evidence truncation lossy in a way that makes answers wrong? Does the system prompt give the LLM enough guardrails to say "I don't have enough data" vs fabricating?
   - **Conversation context**: The `context` dict passes `history`, `last_intent`, `resolved_entities`, `session_entities`, and `summary`. Verify that pronoun resolution ("How about their epics?" after asking about a team) actually works end-to-end.
   - **Error handling**: What happens when the LLM provider is down? Does the rule-based fallback always produce a usable answer, or can it return empty/broken responses?

3. **`backend/services/ai/briefing_service.py`** — Check if the 4-hour cache ever serves stale data after a sync completes. Check the LLM JSON parsing — does it handle malformed LLM output gracefully?

4. **`backend/services/ai/anomaly_service.py`** — IQR-based detection. Check for division-by-zero when a team has no historical data. Check if the 1-hour cache TTL is appropriate or if anomalies could be missed.

5. **`backend/services/ai/prediction_service.py`** — Linear regression for velocity prediction. Check edge cases: teams with < 3 data points, zero-variance data, negative predictions.

6. **`backend/plugins/llm/`** — Review the fallback chain (Anthropic → OpenAI). Does it actually fail over correctly? What happens if both are down? Is there a timeout that could block the event loop?

7. **`frontend/src/components/ChatPanel.tsx`** — Check if conversation context (`session_entities`, `history`) can grow unboundedly over a long chat session. Check if the UI gracefully handles error responses, slow responses, or empty evidence.

## Phase 2: Design Issues (architecture & maintainability)

8. **qa_service.py is 2,712 lines** — This is a god-object. Identify the natural seams where it should be decomposed (intent classifier, entity resolver, evidence fetcher, answer generator, follow-up generator). What's the refactoring strategy that minimizes risk?

9. **Hybrid LLM/rule-based architecture** — The system falls back to rule-based when no LLM is configured. But the rule-based answers are essentially formatted evidence dumps. Is this actually useful to a director, or is it noise? Should the fallback be smarter?

10. **Evidence ranking** — `_EVIDENCE_TYPE_PRIORITY` uses static weights. Should this be dynamic based on the intent? E.g., for `risk` intent, anomaly evidence should outrank team_summary, but for `team_health` the priority might reverse.

11. **Caching strategy** — Briefing (4h), anomalies (1h), predictions (2h), metadata (5min). Are these TTLs well-calibrated? What happens if a director asks "what changed?" right after a GitLab sync but the cache hasn't expired?

12. **Missing capabilities** — What questions would a director naturally ask that the system can't answer well today? E.g.:
    - "Why did velocity drop?" (causal reasoning)
    - "What should I focus on this week?" (prioritization)
    - "Show me the trend for the last quarter" (time-series visualization)
    - "What's blocking the Salesforce team?" (cross-system correlation)

## Phase 3: "Ask Intelligence" Smartness Evaluation

Rate the current system 1-10 on each dimension and provide specific improvement recommendations:

13. **Intent Understanding** — Can it handle:
    - Ambiguous questions ("How are things?")
    - Multi-part questions ("How is eCommerce doing and what epics are at risk?")
    - Negation ("Which teams DON'T have any at-risk epics?")
    - Temporal references ("last month", "since January", "this sprint")
    - Implicit context ("What about Salesforce?" after asking about eCommerce)

14. **Answer Quality** — For each intent type, evaluate:
    - Does it answer the actual question asked, or just dump related data?
    - Does it provide insight or just numbers? (e.g., "Velocity is 12" vs "Velocity is 12, down 30% from last week — this correlates with 2 engineers being on PTO")
    - Does it know when to say "I don't know" vs making up an answer?

15. **Conversation Flow** — Evaluate:
    - Follow-up suggestions: Are they contextually relevant or generic?
    - Pronoun/reference resolution: Does "them", "that team", "their epics" resolve correctly?
    - Memory: After 5+ turns, does the system lose context?

16. **Actionability** — Does the system help the director make decisions, or just report data? What would make it genuinely useful for:
    - Sprint planning prep
    - 1:1 preparation with EMs
    - Stakeholder update drafting
    - Risk triage

## Phase 4: Concrete Recommendations

Provide a prioritized list of improvements (P0/P1/P2) with estimated effort:

- **P0 (bugs/correctness)**: Things that produce wrong answers today
- **P1 (intelligence upgrades)**: Changes that would make the biggest smartness improvement
- **P2 (architecture)**: Structural improvements for long-term maintainability

For each recommendation, provide:
1. What's wrong (with file:line references)
2. Why it matters (impact on user experience)
3. How to fix it (specific code changes or new architecture)
4. Effort estimate (S/M/L)

Focus on being specific and actionable — not generic advice like "add more tests". I want file paths, line numbers, and code-level suggestions.
```

---

*Generated from codebase analysis on 2026-03-05.*
