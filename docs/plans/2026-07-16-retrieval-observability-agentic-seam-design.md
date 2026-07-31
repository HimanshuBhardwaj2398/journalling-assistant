# Design: Retrieval Observability Deepening + Agentic Seam

**Date**: 2026-07-16
**Status**: Approved
**Author**: Himanshu (with Claude)
**Scope**: Amends the [2026-07-13 eval-gated retrieval strategy design](2026-07-13-retrieval-eval-strategy-design.md)
in two places — observability becomes a first-class deliverable of Phase 1, and the Phase-4
agentic layer gets an explicit design seam now. Everything else in that design stands unchanged.

---

## 1. Context

The eval-gated capability ladder (2026-07-13) deliberately deferred Langfuse logging from the
eval runner ("keep the first version simple") and left the Phase-4 agent as a one-line ladder
entry. Two new requirements change that:

1. **Observability is a first-class concern** — debugging retrieval quality and watching eval
   runs should not require print statements or re-runs.
2. **An agentic query-interpretation layer is coming** — Phases 1–3 must not bake in
   assumptions that fight it.

A third requirement — *elegant, simple, refactorable design* — is already satisfied by the
existing plan's port + registry + decorator-adapter shape and needs no amendment.

## 2. Decision 1 — Observability: deepen Langfuse through the existing port

**All tracing continues to flow through `LangfuseTracer`** ([observability/langfuse.py](../../observability/langfuse.py)).
Application code never imports `langfuse` directly — enforced with the same TID251
boundary-lint discipline used for the settings module. The tracer stays optional: unconfigured
environments no-op, tests inject fakes. No new infrastructure.

Four additions, in build order:

### 2a. Nested spans inside `search()`

`RetrievalEngine.search()` keeps its root observation. The stages that are already separate
methods each get a child span with timing and candidate counts:

| Span | Wraps | Records |
|---|---|---|
| `retrieval.semantic` | vector-store query | k, candidate count |
| `retrieval.fts` | PostgreSQL FTS query | k, candidate count, normalized score range |
| `retrieval.fusion` | RRF merge | input list sizes, weights, output size |
| `retrieval.enrich` | chunk-metadata lookup | uuids looked up / resolved |

Langfuse's `start_as_current_observation` nests context-managed spans automatically, so this is
additive — no signature changes.

### 2b. Generation tracing

`LangfuseTracer.observe()` gains an `as_type` passthrough (`"generation"` for LLM calls).
`GroundedAnswerService` / `LLMClient` record model id, token usage (from the litellm response),
and latency per answer. Cost then appears in Langfuse automatically from model + tokens.

### 2c. Eval dataset hosted on Langfuse + runs as dataset experiments *(reverses the phase01 deferral; extended 2026-07-16 evening)*

The eval dataset itself is **synced to Langfuse as a hosted dataset** (`evals/sync.py`): items
upsert by row id (idempotent re-sync), question as input, ground-truth anchors as expected
output, dimensions as metadata. Each `evals.run` execution then creates one **dataset run per
strategy** via the SDK's `run_experiment` (sync in v4): every row becomes a trace with its
per-row metrics (recall@5, MRR, NDCG@10) attached as scores, tagged with git sha + strategy.
Langfuse's dataset-runs view becomes the retriever-comparison UI — strategies side by side,
per-question, clickable into full traces.

**Boundaries that keep this honest:**
- The JSONL in git stays the source of truth. Scoring always reads ground truth from the
  *local* rows (looked up by item id), never from Langfuse's `expected_output` copy — a stale
  sync can't corrupt metrics.
- All Langfuse SDK types stay inside `observability/langfuse.py`: the tracer port gains
  `sync_dataset(...)` and `run_dataset_experiment(...)` taking plain callables and returning
  plain outcomes.
- When Langfuse is unconfigured, the runner falls back to an identical local loop sharing the
  same task and scorer functions, so offline numbers cannot diverge. The results JSON is
  written either way.

### 2d. Playground feedback — unchanged, still deferred

Thumbs up/down → Langfuse scores remains Track 2 (per the 2026-07-13 design §6): it needs real
usage to be worth anything. Not in this round.

## 3. Decision 2 — Agentic seam: design now, build at Phase 4

The Phase-4 ladder entry becomes a concrete shape so earlier phases stay compatible:

```
user message
    │
    ▼
QueryInterpreter (port)              # Phase 4 — LLM-backed; intent, rewrites, filters
    │  InterpretedQuery(intents, queries[], filters, strategy_hint)
    ▼
Agent loop (LangGraph)               # Phase 4 — router + grader + rewrite loops
    │  tools = the retriever registry (+ answerer)
    ▼
GroundedAnswerService
```

- **`QueryInterpreter` port** (sketch, not built now):
  `interpret(user_message: str, history: list[Message] | None) -> InterpretedQuery`.
  It sits *above* retrieval; retrievers never see raw user messages once it exists.
- **The retriever registry is the tool catalog.** Every strategy registered for the eval
  harness is automatically a candidate tool for the agent — this is why the registry (phase01
  Task 3) is worth building carefully.
- **Binding constraint on Phases 1–3**: "user message" and "retrieval query" are distinct
  concepts everywhere. The eval dataset keeps question text separate from any rewriting; no
  API may conflate the two.
- **Eval-gated as ever**: the agent ships only when it beats the Phase-2/3 winner on the
  end-to-end sets (including unanswerable + multi-hop questions, per the 2026-07-13 ladder).

## 4. Execution decisions

- **Branch**: `feature/retrieval-eval-harness-v2`, based on `chore/backlog-round-2` (PR #8),
  with the completed Task-1 commit cherry-picked from the retired
  `feature/retrieval-eval-harness` worktree. The old branch is kept (it carries an unmerged
  docs/learning commit) but its worktree is removed.
- **Plan amendments to the phase01 implementation plan** (local-only — implementation plans
  stay private, only design docs are published):
  - Task 7 (runner) now includes the Langfuse experiment logging (§2c).
  - New task: per-stage spans + generation tracing (§2a, §2b).
  - All other tasks (2–6, 8) proceed as written; Tasks 9–10 remain the manual runbook.

## 5. Not doing (YAGNI, reaffirmed)

- OpenTelemetry abstraction — Langfuse via the one tracer port is enough at this scale.
- A separate local metrics module — per-stage timings already land in `SearchTrace` and spans.
- Agent code, `QueryInterpreter` implementation, or FastAPI — Phase 4, eval-gated.
- Playground feedback widget — Track 2, after real usage accumulates.
