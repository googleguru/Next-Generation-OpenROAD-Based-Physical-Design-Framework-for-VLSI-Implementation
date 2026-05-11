from __future__ import annotations
import logging
from collections import defaultdict
from typing import Any, Optional

from ..core.state_model import FlowStage
from .metric_schema import QoRMetrics, METRIC_REGISTRY

logger = logging.getLogger(__name__)


class CrossStageFeedbackEngine:
    """
    Aggregates per-stage metrics, computes cross-stage signals,
    and emits actionable parameter suggestions for downstream stages.
    """

    def __init__(self, alarm_policy: str = "warn"):
        self.alarm_policy = alarm_policy  # "warn" | "abort" | "retry"
        self._history: dict[FlowStage, list[QoRMetrics]] = defaultdict(list)
        self._failure_log: list[dict] = []

    def ingest(self, stage: FlowStage, metrics: dict[str, Any]) -> QoRMetrics:
        qm = QoRMetrics(stage=stage.value, values=dict(metrics))
        self._history[stage].append(qm)
        self._check_alarms(stage, qm)
        return qm

    def record_failure(self, stage: FlowStage, error: str) -> None:
        self._failure_log.append({"stage": stage.value, "error": error})

    def get_signal(self, for_stage: FlowStage) -> dict[str, Any]:
        signals: dict[str, Any] = {}

        if for_stage == FlowStage.DETAIL_PLACE:
            gp_metrics = self._latest(FlowStage.GLOBAL_PLACE)
            if gp_metrics:
                overflow = gp_metrics.get("overflow", 0.0)
                if isinstance(overflow, float) and overflow > 15.0:
                    signals["reduce_density"] = True
                    signals["density_delta"] = -0.05
                wns = gp_metrics.get("wns", 0.0)
                if isinstance(wns, float) and wns < -0.5:
                    signals["enable_timing_repair"] = True

        elif for_stage == FlowStage.CTS:
            dp_metrics = self._latest(FlowStage.DETAIL_PLACE)
            if dp_metrics:
                wns = dp_metrics.get("wns", 0.0)
                if isinstance(wns, float) and wns < -1.0:
                    signals["cts_timing_aggressive"] = True
                    signals["post_cts_repair"] = True

        elif for_stage == FlowStage.GLOBAL_ROUTE:
            gp_metrics = self._latest(FlowStage.GLOBAL_PLACE)
            if gp_metrics:
                overflow = gp_metrics.get("overflow", 0.0)
                if isinstance(overflow, float) and overflow > 20.0:
                    signals["increase_routing_iter"] = True
                    signals["routing_iter_delta"] = 25

        elif for_stage == FlowStage.DETAIL_ROUTE:
            gr_metrics = self._latest(FlowStage.GLOBAL_ROUTE)
            if gr_metrics:
                overflow = gr_metrics.get("overflow", 0.0)
                if isinstance(overflow, float) and overflow > 5.0:
                    signals["increase_droute_iter"] = True

        elif for_stage == FlowStage.FINISH:
            dr_metrics = self._latest(FlowStage.DETAIL_ROUTE)
            if dr_metrics:
                drc = dr_metrics.get("drc_violations", 0)
                if isinstance(drc, (int, float)) and drc > 0:
                    signals["run_antenna_fix"] = True
                    signals["drc_count"] = int(drc)

        return signals

    def qor_trend(self, metric: str) -> list[tuple[str, float]]:
        trend = []
        for stage in FlowStage.ordered():
            records = self._history.get(stage, [])
            if records:
                val = records[-1].get(metric)
                if val is not None:
                    try:
                        trend.append((stage.value, float(val)))
                    except (TypeError, ValueError):
                        pass
        return trend

    def summary_table(self) -> list[dict[str, Any]]:
        rows = []
        for stage in FlowStage.ordered():
            records = self._history.get(stage, [])
            if not records:
                continue
            last = records[-1]
            row = {"stage": stage.value}
            for key in ("wns", "tns", "overflow", "drc_violations",
                        "wirelength", "utilization"):
                row[key] = last.get(key, "N/A")
            rows.append(row)
        return rows

    def _latest(self, stage: FlowStage) -> Optional[QoRMetrics]:
        records = self._history.get(stage, [])
        return records[-1] if records else None

    def _check_alarms(self, stage: FlowStage, qm: QoRMetrics) -> None:
        critical = qm.critical_alarms()
        if critical:
            msg = "[QoR ALARM] Stage=%s  Critical metrics: %s"
            logger.warning(msg, stage.value, critical)
            if self.alarm_policy == "abort":
                raise RuntimeError(
                    f"QoR alarm triggered abort at {stage.value}: {critical}"
                )
