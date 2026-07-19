"""Agentic query layer: interpret → retrieve → grade → answer/clarify.

LangGraph is used for orchestration only. LLM calls go through
retrieval.llm_client; tracing through observability.langfuse.
See docs/plans/2026-07-16-agentic-rag-v1-design.md (local).
"""
