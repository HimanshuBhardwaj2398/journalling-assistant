# Design: Agent Node Tracing — a `@traced` Decorator for Readable Nodes

**Date**: 2026-07-31
**Status**: Approved
**Author**: Himanshu (with Claude)
**Scope**: A behaviour-preserving readability refactor of the seven graph nodes in
[`agent/nodes.py`](../../agent/nodes.py), built in
[Agentic RAG v1](2026-07-16-agentic-rag-v1-design.md). No change to the graph topology, the
loop's decisions, or what any span reports to Langfuse. The tracer port from the
[observability seam design](2026-07-16-retrieval-observability-agentic-seam-design.md) §2 is
unchanged — this sits one level above it.

---

## 1. Context and the problem

Every node in the agent graph carries the same tracing shell:

```python
def interpret_node(state: AgentState, *, deps: AgentDeps) -> dict:
    with deps.tracer.observe(name="agent.interpret", input=state.user_message) as obs:
        interpreted = deps.interpreter.interpret(state.user_message, history=state.messages)
        obs.update(output=interpreted.model_dump())
        return {"interpreted": interpreted}
```

Two lines of tracing per node is not much on its own. The cost is structural:

- **Every node body is indented one level inside a `with` block.** Across seven nodes this
  reads as ceremony repeated seven times, and it makes the two long nodes harder to scan.
- **Loop logic and trace reporting interleave.** In
  [`retrieve_node`](../../agent/nodes.py#L88-L128), the dedupe-and-merge algorithm, its
  three-line rationale comment, and the `{chunks, new, dropped}` span report all live in one
  35-line `with` body. The reader cannot separate "what the node decides" from "what we tell
  Langfuse."
- **The observation handle is untyped.** `obs` is whatever `deps.tracer` yields — `Any` all
  the way down, in a codebase that otherwise runs mypy over full type hints.

Two properties of the current code are load-bearing and must survive:

1. **Spans open before the work runs.** Input and metadata are attached at `observe()` time,
   so a node that raises mid-body still produces a span carrying what it was given. Moving
   that attachment after the work would lose exactly the context you want when debugging a
   failure.
2. **Span output is richer than the state update.** `retrieve` reports `new` and `dropped`
   counts that exist nowhere in `AgentState`, and `answer` reports a `degraded` marker on its
   empty-retrieval path. Both are pinned by tests
   ([`test_nodes.py:247-259`](../../tests/agent/test_nodes.py#L247-L259) and
   [`:149-158`](../../tests/agent/test_nodes.py#L149-L158)). A design that derives span output
   from the returned update alone would silently drop them.

## 2. Options considered

| Option | Shape | Why not |
|---|---|---|
| **Pure core + traced shell** | Split each node into `_core(state, deps) -> (update, span_report)` plus a four-line traced wrapper. | Cores become tracer-free and trivially testable, but the function count doubles to fourteen and the tuple return is its own ceremony. `retrieve`'s shell would have to re-resolve the retriever to build span metadata before calling the core. |
| **Span table in `graph.py`** | Nodes become pure `(state, deps) -> update`; a `SpanSpec` table and a generic wrapper apply tracing at `add_node` time. | Cleanest `nodes.py` of the three, but span output must be derivable from the state update — which forfeits `retrieve`'s `new`/`dropped` counts and `answer`'s `degraded` marker. A trace-fidelity regression in the module whose whole point is an inspectable loop. |
| **Decorator injecting the span** ✅ | `@traced(name, input=…, metadata=…)` opens the span and passes the handle to the node as a `span` kwarg. | Chosen. Removes the `with` and the indent level from all seven nodes, keeps open-time attachment, and lets each node report what only it knows. |

A fourth shape — a contextvar-backed `current_span()` free function, removing the `span`
parameter entirely — was rejected on house style. This codebase injects its dependencies
(`Database`, `AgentDeps`, the tracer port); action-at-a-distance would be the one exception.

## 3. Design

### 3a. New module: `agent/tracing.py` (~40 lines)

Two exports. A `Span` protocol, which finally gives the observation handle a real type:

```python
class Span(Protocol):
    def update(self, **kwargs: Any) -> None: ...
```

It is structural on purpose: it is satisfied by `LangfuseObservationHandle` and by the test
suite's `FakeTracer` handle without either declaring anything.

And the decorator:

```python
def traced(
    name: str,
    *,
    input: Callable[[AgentState, AgentDeps], Any] | None = None,
    metadata: Callable[[AgentState, AgentDeps], Any] | None = None,
) -> Callable[[TracedNode], Node]:
```

Behaviour:

- Extractors take `(state, deps)`, not just state — `retrieve`'s span metadata needs
  `retriever.name`, which comes from the deps registry.
- Only declared keys are passed to `observe()`, so `clarify`'s span stays as bare as it is
  today rather than gaining `input=None, metadata=None`.
- The node is called with `span=` injected; exceptions propagate untouched, so `run_turn`
  still marks the turn-level span `ERROR`.
- `functools.wraps` preserves `__name__` for tracebacks.

`TracedNode` and `Node` are keyword-aware `Protocol`s rather than `Callable[...]` aliases, so
mypy checks both sides of the decorator. `AgentDeps` is imported under `TYPE_CHECKING` to keep
`nodes.py → tracing.py` acyclic. The module lives in `agent/` rather than `observability/`
because it knows `AgentState`; it touches only the tracer port, never a Langfuse SDK type, so
the seam design's rule that SDK types stay inside `observability/langfuse.py` still holds.

### 3b. Node bodies

`graph.py` is untouched — `partial(node, deps=deps)` binds exactly as before, since the
decorated signature is still `(state, *, deps)`.

```python
@traced("agent.answer", metadata=lambda s, d: {"chunks": len(s.retrieved)})
def answer_node(state: AgentState, *, deps: AgentDeps, span: Span) -> dict:
    if not state.retrieved:
        logger.warning("answer_node reached with no retrieved chunks; clarifying")
        span.update(output=DEFAULT_CLARIFYING_QUESTION,
                    metadata={"degraded": "empty_retrieval"})
        return {"outcome": "clarify", "final_text": DEFAULT_CLARIFYING_QUESTION}
    response = deps.answer_service.answer(state.user_message, state.retrieved)
    span.update(output=response.answer)
    return {"outcome": "answer", "final_text": response.answer,
            "citations": list(response.citations)}
```

Five of the seven nodes convert with a one-line declaration and nothing else.

### 3c. The two nodes that compute their own span input

`retrieve` and `rewrite` open their spans with values the body also computes — the resolved
queries and the rewrite prompt. Since spans must open *before* the work (§1), those values
cannot come from a post-hoc `span.update()`. Rather than duplicate the logic inside a lambda,
each gets a small named pure helper that both the extractor and the body call:

- `_resolve_retriever(state, deps) -> tuple[list[str], Retriever]`
- `_rewrite_prompt(state) -> str`

Both are dict lookups and string formatting, so calling them twice per node costs nothing
measurable. `_grader_prompt(state) -> str` gets extracted alongside for symmetry, even though
`grade`'s span input is derivable from state directly. This falls out of the tracing work
rather than being scope creep: the message-building blocks were the other readability
complaint in `nodes.py`, and naming them is what makes the extractor lambdas honest.

## 4. Trace fidelity and test impact

The resulting Langfuse observation is identical to today's for all seven nodes: same names,
same open-time input and metadata, same `update` payloads — including `answer`'s `degraded`
marker and `retrieve`'s `new`/`dropped` counts.

**All 20 existing node tests must pass unchanged**, including the two that pin span behaviour.
This is the acceptance criterion for the refactor: if a node test needs editing, the change
drifted from behaviour-preserving and should be reworked, not the test.

New tests in `tests/agent/test_tracing.py`, written first:

- the span opens before the node body executes,
- an exception in the body propagates while the span still closes,
- extractors receive both state and deps,
- undeclared kwargs are omitted from the `observe()` call.

## 5. Non-goals

- **`service.py`'s `agent.turn` span** — different shape; it reads `trace_url`/`trace_id` off
  the handle after the block and owns the error path.
- **The `retrieval/` tracing call sites** — class methods with a different signature shape;
  the decorator is node-specific by design.
- **Typing `AgentDeps`' six `Any` fields** — worth doing, separate change.
- **Moving the four system prompts to their own module** — worth doing, separate change.
- **Any behaviour change to the loop** — no new nodes, edges, retries, or degradation paths.
