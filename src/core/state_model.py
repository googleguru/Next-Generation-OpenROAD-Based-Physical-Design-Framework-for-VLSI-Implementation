from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class FlowStage(str, Enum):
    SYNTHESIS = "synthesis"
    FLOORPLAN = "floorplan"
    PDN = "pdn"
    GLOBAL_PLACE = "global_place"
    DETAIL_PLACE = "detail_place"
    CTS = "cts"
    GLOBAL_ROUTE = "global_route"
    DETAIL_ROUTE = "detail_route"
    FINISH = "finish"

    @classmethod
    def ordered(cls) -> list["FlowStage"]:
        return [
            cls.SYNTHESIS, cls.FLOORPLAN, cls.PDN,
            cls.GLOBAL_PLACE, cls.DETAIL_PLACE, cls.CTS,
            cls.GLOBAL_ROUTE, cls.DETAIL_ROUTE, cls.FINISH,
        ]

    def next(self) -> "FlowStage | None":
        order = FlowStage.ordered()
        idx = order.index(self)
        return order[idx + 1] if idx + 1 < len(order) else None

    def prev(self) -> "FlowStage | None":
        order = FlowStage.ordered()
        idx = order.index(self)
        return order[idx - 1] if idx > 0 else None


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"


@dataclass
class StageRecord:
    stage: FlowStage
    status: StageStatus = StageStatus.PENDING
    start_time: float = 0.0
    end_time: float = 0.0
    retry_count: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
    params_used: dict[str, Any] = field(default_factory=dict)
    error_msg: str = ""
    log_path: Path | None = None

    @property
    def runtime_s(self) -> float:
        if self.end_time and self.start_time:
            return self.end_time - self.start_time
        return 0.0


@dataclass
class DesignState:
    design_name: str
    run_id: str
    work_dir: Path
    seed: int = 42

    stage_records: dict[FlowStage, StageRecord] = field(default_factory=dict)
    current_stage: FlowStage | None = None
    global_params: dict[str, Any] = field(default_factory=dict)
    flow_start: float = field(default_factory=time.time)

    def __post_init__(self):
        for s in FlowStage.ordered():
            self.stage_records[s] = StageRecord(stage=s)

    def record(self, stage: FlowStage) -> StageRecord:
        return self.stage_records[stage]

    def mark_running(self, stage: FlowStage) -> StageRecord:
        rec = self.stage_records[stage]
        rec.status = StageStatus.RUNNING
        rec.start_time = time.time()
        self.current_stage = stage
        return rec

    def mark_done(self, stage: FlowStage, metrics: dict[str, Any],
                  params: dict[str, Any]) -> StageRecord:
        rec = self.stage_records[stage]
        rec.status = StageStatus.SUCCESS
        rec.end_time = time.time()
        rec.metrics = metrics
        rec.params_used = params
        return rec

    def mark_failed(self, stage: FlowStage, error: str) -> StageRecord:
        rec = self.stage_records[stage]
        rec.status = StageStatus.FAILED
        rec.end_time = time.time()
        rec.error_msg = error
        return rec

    def mark_skipped(self, stage: FlowStage, reason: str = "") -> StageRecord:
        rec = self.stage_records[stage]
        rec.status = StageStatus.SKIPPED
        rec.error_msg = reason
        return rec

    def total_runtime(self) -> float:
        return time.time() - self.flow_start

    def completed_stages(self) -> list[FlowStage]:
        return [s for s, r in self.stage_records.items()
                if r.status == StageStatus.SUCCESS]

    def failed_stages(self) -> list[FlowStage]:
        return [s for s, r in self.stage_records.items()
                if r.status == StageStatus.FAILED]

    def is_flow_complete(self) -> bool:
        return FlowStage.FINISH in self.completed_stages()

    def get_latest_metrics(self) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        for stage in FlowStage.ordered():
            rec = self.stage_records.get(stage)
            if rec and rec.metrics:
                metrics.update(rec.metrics)
        return metrics
