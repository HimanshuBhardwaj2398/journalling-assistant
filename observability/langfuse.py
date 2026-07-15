"""Optional Langfuse tracing helpers for the query layer."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterator, Optional, Sequence

from config.settings import LangfuseSettings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatasetItemSpec:
    """SDK-free description of one hosted dataset item (upserted by id)."""

    id: str
    input: Any
    expected_output: Any = None
    metadata: Any = None


@dataclass
class LangfuseObservationHandle:
    """Lightweight wrapper around an active Langfuse observation."""

    enabled: bool = False
    trace_id: Optional[str] = None
    trace_url: Optional[str] = None
    provider: str = "langfuse"
    _observation: Any = None
    _client: Any = None

    def update(self, **kwargs: Any) -> None:
        """Safely update the underlying observation if tracing is active."""
        if not self.enabled or self._observation is None:
            return

        clean_kwargs = {key: value for key, value in kwargs.items() if value is not None}
        if not clean_kwargs:
            return

        update_fn = getattr(self._observation, "update", None)
        if not callable(update_fn):
            return

        try:
            update_fn(**clean_kwargs)
            self._refresh_trace_link()
        except Exception as exc:  # pragma: no cover - defensive logging path
            logger.warning("Langfuse observation update failed: %s", exc)

    def score(
        self,
        *,
        name: str,
        value: Any,
        data_type: str = "NUMERIC",
        comment: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Safely attach a score to the active observation."""
        if not self.enabled or self._observation is None:
            return

        score_fn = getattr(self._observation, "score", None)
        if not callable(score_fn):
            return

        try:
            score_fn(
                name=name,
                value=value,
                data_type=data_type,
                comment=comment,
                metadata=metadata,
            )
        except Exception as exc:  # pragma: no cover - defensive logging path
            logger.warning("Langfuse observation scoring failed: %s", exc)

    def _refresh_trace_link(self) -> None:
        """Refresh trace metadata from the Langfuse client."""
        if self._client is None:
            return

        trace_id_fn = getattr(self._client, "get_current_trace_id", None)
        if callable(trace_id_fn):
            try:
                self.trace_id = trace_id_fn()
            except Exception:  # pragma: no cover - defensive logging path
                pass

        trace_url_fn = getattr(self._client, "get_trace_url", None)
        if callable(trace_url_fn):
            try:
                self.trace_url = trace_url_fn()
            except TypeError:
                if self.trace_id:
                    try:
                        self.trace_url = trace_url_fn(self.trace_id)
                    except Exception:  # pragma: no cover - defensive logging path
                        pass
            except Exception:  # pragma: no cover - defensive logging path
                pass


class LangfuseTracer:
    """Lazy, optional Langfuse tracer for retrieval and answer flows."""

    def __init__(
        self,
        client: Any = None,
        settings: Optional[LangfuseSettings] = None,
    ) -> None:
        self._settings = settings or get_settings().langfuse
        self._client = client if client is not None else self._build_client()

    @property
    def enabled(self) -> bool:
        """Return True when Langfuse tracing is active."""
        return self._client is not None

    @contextmanager
    def observe(
        self,
        *,
        name: str,
        input: Any = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Iterator[LangfuseObservationHandle]:
        """Create an observation context if Langfuse is configured."""
        if self._client is None:
            yield LangfuseObservationHandle(enabled=False)
            return

        try:
            observation_context = self._client.start_as_current_observation(
                name=name,
                input=input,
                metadata=metadata,
            )
        except Exception as exc:  # pragma: no cover - defensive logging path
            logger.warning("Could not start Langfuse observation '%s': %s", name, exc)
            yield LangfuseObservationHandle(enabled=False)
            return

        try:
            with observation_context as observation:
                handle = LangfuseObservationHandle(
                    enabled=True,
                    _observation=observation,
                    _client=self._client,
                )
                handle._refresh_trace_link()
                yield handle
        finally:
            self.flush()

    def sync_dataset(
        self,
        *,
        name: str,
        items: Sequence[DatasetItemSpec],
        description: Optional[str] = None,
    ) -> Optional[int]:
        """Upsert a hosted dataset from item specs. Returns items synced, None when disabled.

        Items upsert by id, so re-syncing after local edits is idempotent. Per-item
        failures are logged and skipped — a partial sync is repairable by re-running.
        """
        if self._client is None:
            return None

        try:
            self._client.create_dataset(name=name, description=description)
        except Exception as exc:  # dataset may already exist — items are the real work
            logger.info("create_dataset(%s): %s", name, exc)

        synced = 0
        for item in items:
            try:
                self._client.create_dataset_item(
                    dataset_name=name,
                    id=item.id,
                    input=item.input,
                    expected_output=item.expected_output,
                    metadata=item.metadata,
                )
                synced += 1
            except Exception as exc:
                logger.warning("dataset item %s failed to sync: %s", item.id, exc)
        return synced

    def flush(self) -> None:
        """Flush buffered traces if the client supports it."""
        if self._client is None:
            return

        flush_fn = getattr(self._client, "flush", None)
        if callable(flush_fn):
            try:
                flush_fn()
            except Exception as exc:  # pragma: no cover - defensive logging path
                logger.warning("Langfuse flush failed: %s", exc)

    def _build_client(self) -> Any:
        """Instantiate the Langfuse client if configuration is present."""
        if not self._settings.is_configured:
            return None

        try:
            from langfuse import Langfuse
        except ImportError:
            logger.info(
                "Langfuse tracing is configured but the SDK is not installed. "
                "Install the 'langfuse' package to enable tracing."
            )
            return None

        try:
            return Langfuse(
                public_key=self._settings.public_key,
                secret_key=self._settings.secret_key,
                base_url=self._settings.base_url,
                tracing_enabled=self._settings.tracing_enabled,
                environment=self._settings.tracing_environment,
                release=self._settings.release,
            )
        except Exception as exc:  # pragma: no cover - defensive logging path
            logger.warning("Failed to initialize Langfuse client: %s", exc)
            return None


@lru_cache()
def get_langfuse_tracer() -> LangfuseTracer:
    """Return a cached Langfuse tracer instance."""
    return LangfuseTracer()
