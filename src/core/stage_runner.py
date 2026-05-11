from __future__ import annotations
import logging
import time
from pathlib import Path
from typing import Any, Callable

from .state_model import DesignState, FlowStage, StageStatus
from .artifact_registry import ArtifactRegistry

logger = logging.getLogger(__name__)


class StageRunnerError(Exception):
    pass


class StageRunner:
    def __init__(
        self,
        state: DesignState,
        registry: ArtifactRegistry,
        max_retries: int = 2,
        retry_delay_s: float = 5.0,
    ):
        self.state = state
        self.registry = registry
        self.max_retries = max_retries
        self.retry_delay_s = retry_delay_s
        self._hooks: dict[str, list[Callable]] = {
            "pre_stage": [], "post_stage": [], "on_failure": []
        }

    def add_hook(self, event: str, fn: Callable) -> None:
        if event in self._hooks:
            self._hooks[event].append(fn)

    def _fire(self, event: str, **kwargs) -> None:
        for fn in self._hooks.get(event, []):
            try:
                fn(**kwargs)
            except Exception as exc:
                logger.warning("Hook %s raised: %s", event, exc)

    def run_stage(
        self,
        stage: FlowStage,
        execute_fn: Callable[..., dict[str, Any]],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        rec = self.state.mark_running(stage)
        log_path = self.registry.stage_dir(stage) / "stage.log"
        rec.log_path = log_path

        self._fire("pre_stage", stage=stage, params=params, state=self.state)

        attempt = 0
        last_error = ""
        while attempt <= self.max_retries:
            try:
                logger.info("[%s] attempt %d/%d", stage.value, attempt + 1,
                            self.max_retries + 1)
                metrics = execute_fn(stage=stage, params=params,
                                     work_dir=self.registry.stage_dir(stage))
                self.state.mark_done(stage, metrics, params)
                self._fire("post_stage", stage=stage, metrics=metrics,
                           state=self.state)
                logger.info("[%s] SUCCESS  rt=%.1fs",
                            stage.value, rec.runtime_s)
                return metrics

            except StageRunnerError as exc:
                last_error = str(exc)
                attempt += 1
                rec.retry_count = attempt
                logger.warning("[%s] attempt %d failed: %s",
                               stage.value, attempt, last_error)
                if attempt <= self.max_retries:
                    time.sleep(self.retry_delay_s)
                    params = self._escalate_params(stage, params, attempt)

        self.state.mark_failed(stage, last_error)
        self._fire("on_failure", stage=stage, error=last_error, state=self.state)
        raise StageRunnerError(
            f"Stage {stage.value} failed after {self.max_retries + 1} attempts: {last_error}"
        )

    def _escalate_params(
        self, stage: FlowStage, params: dict[str, Any], attempt: int
    ) -> dict[str, Any]:
        updated = dict(params)
        if stage == FlowStage.GLOBAL_PLACE:
            current = float(updated.get("target_density", 0.70))
            updated["target_density"] = max(0.50, current - 0.05 * attempt)
        elif stage == FlowStage.CTS:
            updated["cts_buf_distance"] = int(
                updated.get("cts_buf_distance", 100) * 1.2
            )
        elif stage == FlowStage.GLOBAL_ROUTE:
            current = int(updated.get("routing_overflow_iter", 50))
            updated["routing_overflow_iter"] = current + 25 * attempt
        elif stage == FlowStage.DETAIL_ROUTE:
            current = int(updated.get("droute_end_iter", 64))
            updated["droute_end_iter"] = min(256, current + 32 * attempt)
        return updated

    def skip_stage(self, stage: FlowStage, reason: str) -> None:
        self.state.mark_skipped(stage, reason)
        logger.info("[%s] SKIPPED: %s", stage.value, reason)

    def is_done(self, stage: FlowStage) -> bool:
        return self.state.record(stage).status == StageStatus.SUCCESS

    def can_run(self, stage: FlowStage) -> bool:
        prev = stage.prev()
        if prev is None:
            return True
        prev_rec = self.state.record(prev)
        return prev_rec.status in (StageStatus.SUCCESS, StageStatus.SKIPPED)
