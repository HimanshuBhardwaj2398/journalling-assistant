"""Tests for pipeline progress callback."""

import asyncio
from unittest.mock import MagicMock

from core.interfaces import PipelineContext, PipelineStage, StageStatus


class FakeStage(PipelineStage):
    """Minimal stage for testing."""

    def __init__(self, stage_name: str, deps=None):
        self._name = stage_name
        self._deps = deps or []

    @property
    def name(self) -> str:
        return self._name

    @property
    def required_stages(self):
        return self._deps

    async def execute(self, context: PipelineContext) -> PipelineContext:
        return context.mark_stage_completed(self.name)


class TestPipelineCallback:
    def test_callback_called_for_each_stage(self):
        """Callback receives stage_name and status for each stage transition."""
        from ingestion.orchestrator import PipelineOrchestrator

        callback = MagicMock()
        stages = [FakeStage("stage_a"), FakeStage("stage_b", deps=["stage_a"])]
        pipeline = PipelineOrchestrator(stages)

        context = PipelineContext()
        asyncio.run(pipeline.execute(context, on_stage_update=callback))

        # Should be called with running + completed for each stage = 4 calls
        assert callback.call_count == 4
        callback.assert_any_call("stage_a", StageStatus.RUNNING)
        callback.assert_any_call("stage_a", StageStatus.COMPLETED)
        callback.assert_any_call("stage_b", StageStatus.RUNNING)
        callback.assert_any_call("stage_b", StageStatus.COMPLETED)

    def test_callback_receives_failed_status(self):
        """Callback receives FAILED status when a stage fails."""
        from ingestion.orchestrator import PipelineOrchestrator

        class FailingStage(PipelineStage):
            @property
            def name(self):
                return "bad_stage"

            @property
            def required_stages(self):
                return []

            async def execute(self, context):
                raise ValueError("something broke")

        callback = MagicMock()
        pipeline = PipelineOrchestrator([FailingStage()])
        context = PipelineContext()
        asyncio.run(pipeline.execute(context, on_stage_update=callback))

        callback.assert_any_call("bad_stage", StageStatus.RUNNING)
        callback.assert_any_call("bad_stage", StageStatus.FAILED)

    def test_no_callback_is_fine(self):
        """Pipeline works without callback (backward compatible)."""
        from ingestion.orchestrator import PipelineOrchestrator

        stages = [FakeStage("stage_a")]
        pipeline = PipelineOrchestrator(stages)
        context = PipelineContext()
        result = asyncio.run(pipeline.execute(context))
        assert result.stage_results["stage_a"] == StageStatus.COMPLETED
