"""Span plumbing for graph nodes.

Nodes declare their span with ``@traced`` and receive the handle as ``span``.
The tracer port itself (``observability/langfuse.py``) is unchanged, and no
Langfuse SDK type crosses this module — it only speaks to the port.
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol

from agent.state import AgentState

if TYPE_CHECKING:  # import-time cycle: nodes.py imports this module
    from agent.nodes import AgentDeps


class Span(Protocol):
    """The observation handle a node reports to.

    Structural on purpose: satisfied by LangfuseObservationHandle and by the
    test suite's fake handle without either declaring anything.
    """

    def update(self, **kwargs: Any) -> None: ...


class TracedNode(Protocol):
    """A node as written: it receives its span handle."""

    def __call__(self, state: AgentState, *, deps: AgentDeps, span: Span) -> dict: ...


class Node(Protocol):
    """A node as the graph sees it: the span is bound by @traced."""

    def __call__(self, state: AgentState, *, deps: AgentDeps) -> dict: ...


Extractor = Callable[[AgentState, "AgentDeps"], Any]


def traced(
    name: str,
    *,
    input: Optional[Extractor] = None,
    metadata: Optional[Extractor] = None,
) -> Callable[[TracedNode], Node]:
    """Open a tracer span around a node and inject the handle as ``span``.

    ``input`` and ``metadata`` are evaluated *before* the node runs, so a node
    that raises mid-body still leaves a span carrying what it was given.
    Undeclared keys are omitted from the ``observe()`` call rather than passed
    as None, keeping bare spans bare. Exceptions propagate untouched: the
    turn-level span in ``service.py`` owns the ERROR marking.
    """

    def decorate(node: TracedNode) -> Node:
        @functools.wraps(node)
        def wrapper(state: AgentState, *, deps: AgentDeps) -> dict:
            observe_kwargs: dict[str, Any] = {"name": name}
            if input is not None:
                observe_kwargs["input"] = input(state, deps)
            if metadata is not None:
                observe_kwargs["metadata"] = metadata(state, deps)
            with deps.tracer.observe(**observe_kwargs) as span:
                return node(state, deps=deps, span=span)

        return wrapper

    return decorate
