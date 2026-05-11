from __future__ import annotations
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from .state_model import DesignState, FlowStage, StageStatus
from .stage_runner import StageRunner, StageRunnerError
from .artifact_registry import ArtifactRegistry

logger = logging.getLogger(__name__)


class FlowController:
    """
    Top-level orchestrator: drives a design through all physical-design stages,
    wires in adaptive tuning, cross-stage QoR feedback, and failure diagnostics.
    """

    def __init__(
        self,
        design_name: str,
        work_dir: Path,
        config: dict[str, Any],
        seed: int = 42,
        run_id: Optional[str] = None,
    ):
        self.run_id = run_id or f"{design_name}_{int(time.time())}_{seed}"
        work_dir = Path(work_dir) / self.run_id
        work_dir.mkdir(parents=True, exist_ok=True)

        self.state = DesignState(
            design_name=design_name,
            run_id=self.run_id,
            work_dir=work_dir,
            seed=seed,
        )
        self.registry = ArtifactRegistry(work_dir)
        self.runner = StageRunner(
            state=self.state,
            registry=self.registry,
            max_retries=config.get("max_retries", 2),
        )
        self.config = config
        self._stage_executors: dict[FlowStage, Any] = {}
        self._tuner: Any = None
        self._feedback: Any = None
        self._diagnostics: Any = None
        self._storage: Any = None

    def register_executor(self, stage: FlowStage, executor: Any) -> None:
        self._stage_executors[stage] = executor

    def attach_tuner(self, tuner: Any) -> None:
        self._tuner = tuner
        self.runner.add_hook("post_stage", self._tuner_post_hook)

    def attach_feedback(self, feedback_engine: Any) -> None:
        self._feedback = feedback_engine
        self.runner.add_hook("post_stage", self._feedback_post_hook)
        self.runner.add_hook("on_failure", self._feedback_fail_hook)

    def attach_diagnostics(self, diag: Any) -> None:
        self._diagnostics = diag
        self.runner.add_hook("on_failure", self._diagnostics_hook)

    def attach_storage(self, storage: Any) -> None:
        self._storage = storage

    def _tuner_post_hook(self, stage: FlowStage, metrics: dict,
                         state: DesignState) -> None:
        if self._tuner:
            next_stage = stage.next()
            if next_stage and next_stage in self._stage_executors:
                suggested = self._tuner.suggest(
                    stage=next_stage,
                    current_metrics=metrics,
                    history=state.get_latest_metrics(),
                )
                self.config.setdefault("stage_params", {})[next_stage.value] = suggested

    def _feedback_post_hook(self, stage: FlowStage, metrics: dict,
                            state: DesignState) -> None:
        if self._feedback:
            self._feedback.ingest(stage, metrics)

    def _feedback_fail_hook(self, stage: FlowStage, error: str,
                            state: DesignState) -> None:
        if self._feedback:
            self._feedback.record_failure(stage, error)

    def _diagnostics_hook(self, stage: FlowStage, error: str,
                          state: DesignState) -> None:
        if self._diagnostics:
            report = self._diagnostics.classify_and_report(stage, error, state)
            log_path = self.registry.stage_dir(stage) / "diagnosis.txt"
            log_path.write_text(report)
            logger.warning("[DIAG] %s\n%s", stage.value, report)

    def run(
        self,
        start_stage: FlowStage = FlowStage.SYNTHESIS,
        end_stage: FlowStage = FlowStage.FINISH,
        skip_stages: Optional[list[FlowStage]] = None,
    ) -> DesignState:
        skip_stages = skip_stages or []
        order = FlowStage.ordered()
        start_idx = order.index(start_stage)
        end_idx = order.index(end_stage)
        stages_to_run = order[start_idx: end_idx + 1]

        logger.info("=== Flow start: %s  run_id=%s ===",
                    self.state.design_name, self.run_id)

        for stage in stages_to_run:
            if stage in skip_stages:
                self.runner.skip_stage(stage, "explicitly skipped by caller")
                continue
            if not self.runner.can_run(stage):
                self.runner.skip_stage(stage, "prerequisite stage not complete")
                continue

            executor = self._stage_executors.get(stage)
            if executor is None:
                self.runner.skip_stage(stage, "no executor registered")
                continue

            params = self._resolve_params(stage)
            try:
                self.runner.run_stage(stage, executor.execute, params)
            except StageRunnerError as exc:
                logger.error("Flow halted at %s: %s", stage.value, exc)
                if self._storage:
                    self._storage.save(self.state)
                return self.state

            if self._storage:
                self._storage.checkpoint(self.state, stage)

        logger.info("=== Flow complete: %s  total_rt=%.1fs ===",
                    self.state.design_name, self.state.total_runtime())
        if self._storage:
            self._storage.save(self.state)
        return self.state

    def rollback_to(self, stage: FlowStage) -> None:
        snapshot_dir = self.state.work_dir / "snapshots"
        if self.registry.restore_snapshot(stage, snapshot_dir):
            rec = self.state.record(stage)
            rec.status = StageStatus.ROLLED_BACK
            logger.info("Rolled back to stage: %s", stage.value)
        else:
            logger.warning("No snapshot found for stage: %s", stage.value)

    def _resolve_params(self, stage: FlowStage) -> dict[str, Any]:
        base = dict(self.config.get("stage_defaults", {}).get(stage.value, {}))
        override = dict(self.config.get("stage_params", {}).get(stage.value, {}))
        base.update(override)
        base["seed"] = self.state.seed
        base["design_name"] = self.state.design_name
        base["run_id"] = self.run_id
        return base

    def summary(self) -> dict[str, Any]:
        records = {}
        for stage, rec in self.state.stage_records.items():
            records[stage.value] = {
                "status": rec.status.value,
                "runtime_s": rec.runtime_s,
                "retries": rec.retry_count,
                "metrics": rec.metrics,
            }
        return {
            "run_id": self.run_id,
            "design": self.state.design_name,
            "seed": self.state.seed,
            "total_runtime_s": self.state.total_runtime(),
            "is_complete": self.state.is_flow_complete(),
            "stages": records,
        }
