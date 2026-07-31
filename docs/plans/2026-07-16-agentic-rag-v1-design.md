# Design: Agentic RAG v1 — Query Understanding, Decider Loop, Model Routing

**Date**: 2026-07-16
**Status**: Approved
**Author**: Himanshu (with Claude)
**Scope**: Builds the Phase-4 agentic layer sketched in the
[2026-07-16 agentic seam design](2026-07-16-retrieval-observability-agentic-seam-design.md) §3,
started early as an **experimental track**. The eval gate from that design stands: the agent
does not replace plain RAG as default until it beats the Phase-2/3 winner on the end-to-end
sets. One amendment: the seam's "Agent loop (LangGraph)" sketch is now a decision, with
LangGraph used for orchestration only.

---

## 1. Context and goals

The retrieval layer has four eval-baselined strategies behind a `Retriever` port + registry,
a multi-provider `LLMClient` (litellm: groq/ollama/openai) with Langfuse generation tracing,
and per-stage retrieval spans. The next layer up is the agent: query understanding, a
tool-using loop, a sufficiency decider that can ask the user a clarifying question, and
grounded answer generation.

Decisions made in brainstorming (2026-07-16):

| Question | Decision |
|---|---|
| V1 tool scope | **Retrieval only.** Web search / YouTube MCP are later tools behind the same seam. |
| Primary goal | **Learning-first** — mechanics stay visible and inspectable. |
| Surface | **Streamlit page, simple turns** — agent returns answer *or* clarifying question; history rides back in. No pause/resume state. |
| Model tiers | **Local Ollama (qwen3, gemma) → Groq OSS → OpenAI** fallback ladder. |
| Framework | **LangGraph from day one** (orchestration only; LLM calls stay on `LLMClient`). |

## 2. Research notes (2026-07)

- **qwen3-8B** is the most reliable local tool/structured-output model in 2026 (native tool
  tokens, valid JSON on 8 GB); **gemma3 is weak at tool calling** — usable only as an
  alternate local *answerer*, never for interpreter/grader roles.
  ([Morph benchmarks](https://www.morphllm.com/best-ollama-models),
  [Local AI Master](https://localaimaster.com/blog/best-ollama-models-tool-calling))
- **Groq OSS tier**: `llama-3.1-8b-instant` (fast/cheap), `llama-3.3-70b-versatile`,
  `gpt-oss-120b`; free tier covers all ([Groq models](https://console.groq.com/docs/models)).
- **litellm Auto Router v2** exists (complexity-tier routing) but is proxy-grade machinery;
  explicit role→model mapping is deterministic and testable — auto-routing is a later,
  eval-gated upgrade ([Auto Router v2](https://docs.litellm.ai/blog/autorouter-v2)).
- Framework survey (PydanticAI / LangGraph / smolagents): PydanticAI's OTel/Logfire
  instrumentation rubs against the Langfuse-only tracer port; smolagents' code-agent paradigm
  is a mismatch; LangGraph fits the graph shape and the existing langchain dependency.
  ([KDnuggets 2026](https://www.kdnuggets.com/10-agentic-ai-frameworks-you-should-know-in-2026),
  [Fastio comparison](https://fast.io/resources/best-ai-agent-frameworks-for-python/))

## 3. Architecture

One LangGraph `StateGraph`, five nodes, two conditional edges:

```
START → interpret ──chit-chat/out-of-scope──→ respond_direct → END
           │
     corpus question
           ▼
        retrieve → grade ──sufficient──→ answer → END
           ▲          │
           │          ├─ insufficient, iterations < 2 → rewrite ─┐
           │          └─ insufficient, budget exhausted → clarify → END
           └─────────────────────────────────────────────────────┘
```

### Nodes

- **interpret** — implements the `QueryInterpreter` port (seam design §3). Small model,
  structured output `InterpretedQuery(intent, queries[], strategy_hint)`. The raw user
  message never reaches a retriever (binding constraint, preserved).
- **retrieve** — no LLM. Uses the retriever registry; strategy = eval-winning default unless
  `strategy_hint` overrides. Results accumulate across iterations, deduped by chunk UUID.
- **grade** — the decider. Small model, structured `SufficiencyGrade(sufficient,
  missing_info, clarifying_question)`. Produces the clarifying question itself when
  insufficient, so **clarify** is pure formatting (no extra LLM call).
- **answer** — reuses `GroundedAnswerService` unchanged (large model).
- **respond_direct** — chit-chat/out-of-scope short-circuit, small model, no retrieval.

### State and code shape

`AgentState` (Pydantic): `messages`, `user_message`, `interpreted`, `retrieved`, `grade`,
`iterations`, `outcome`. Nodes are plain functions over state with injected deps (client,
registry, tracer) — unit-testable without the graph; `graph.py` is pure wiring.

```
agent/
  state.py        # AgentState, InterpretedQuery, SufficiencyGrade
  interpreter.py  # QueryInterpreter port + LLM implementation
  nodes.py        # node functions (deps injected)
  graph.py        # StateGraph wiring + compile
  router.py       # role→model resolution over LLMSettings
views/agent_playground.py
```

New dependency: `langgraph` only. LangSmith/LangChain-callback tracing stays disabled.

## 4. Model routing

Explicit role→model map (extension of `LLMSettings`), not an auto-router:

| Role | Default | Tier |
|---|---|---|
| `interpreter` | `ollama/qwen3:8b` | local |
| `grader` | `ollama/qwen3:8b` | local |
| `answerer` | `groq/llama-3.3-70b-versatile` | Groq OSS |

Each role resolves to an `LLMClient` carrying a litellm **fallback chain
local → Groq → OpenAI** (Ollama down or persistent bad output ⇒ automatic escalation).
Every role repoints with one env var (e.g. `LLM_ROLE_GRADER=groq/llama-3.1-8b-instant`).

## 5. UI flow (Streamlit)

`views/agent_playground.py` beside the RAG playground. Transcript in `st.session_state`;
each user message = one `graph.invoke(state)` with full history. Assistant turn renders one
of: grounded answer (existing citation display), clarifying question, or direct reply. A
per-turn debug expander shows interpreted query, strategy, grade verdict, iterations, and
resolved model per role. Langfuse trace link in the sidebar.

## 6. Observability

All through the existing tracer port; `langfuse` imports stay inside
`observability/langfuse.py`. Trace shape per turn:

```
agent.turn (root: user message → outcome + final text)
├── agent.interpret   (generation: role, resolved model, tokens)
├── agent.retrieve    (wraps existing per-stage retrieval spans)
├── agent.grade       (generation: verdict, missing_info)
├── agent.rewrite     (iteration 2 only)
└── agent.answer      (existing GroundedAnswerService span)
```

Root metadata: iterations, route taken, fallback escalations. Per-generation resolved model
makes Langfuse's cost view the per-tier routing dashboard for free.

## 7. Error handling

- **Malformed structured output**: one retry with the validation error fed back → litellm
  fallback escalates a tier → graceful degraded reply; span records the error. A turn never
  crashes the page.
- **Ollama unreachable**: fallback chain absorbs it; warning logged (visible Groq spend on
  small-model work is the tell).
- **Empty retrieval**: grade sees zero chunks → insufficient → rewrite or clarify. No
  special case.
- **Loop budget**: hard cap of 2 rewrite iterations (config).

## 8. Testing & eval gate

- Unit: each node with fake client/tracer injection (existing pattern); parser tests for
  both structured-output schemas including sloppy-JSON from small models.
- Graph: scripted fake LLMs drive all four paths (direct, answer, rewrite→answer, clarify)
  through the compiled graph.
- **Eval gate**: agent stays experimental until it beats the Phase-2/3 winner on the
  end-to-end sets (incl. unanswerable + multi-hop). Wiring the agent into `evals.run` as a
  fifth "strategy" is a fast follow, not v1.

## 9. Not doing in v1 (YAGNI)

- Web search / YouTube MCP tools (the registry is the tool seam; they slot in later)
- litellm auto-complexity routing
- LangGraph checkpointer, interrupts, persistence
- Conversation memory beyond the Streamlit session
- FastAPI layer, token streaming, multi-agent anything
