from __future__ import annotations
import logging
from typing import Any

from ..core.state_model import FlowStage
from .search_space import SearchSpace

logger = logging.getLogger(__name__)


class RuleBasedTuner:
    """
    Deterministic rule engine: inspects post-stage metrics and emits
    parameter adjustments for the next stage.  No ML, fully auditable.
    """

    def __init__(self, space: SearchSpace | None = None):
        self.space = space
        self._iteration: dict[FlowStage, int] = {}

    def suggest(
        self,
        stage: FlowStage,
        current_metrics: dict[str, Any],
        history: dict[str, Any],
    ) -> dict[str, Any]:
        self._iteration[stage] = self._iteration.get(stage, 0) + 1
        iter_n = self._iteration[stage]

        suggestions: dict[str, Any] = {}
        dispatch = {
            FlowStage.GLOBAL_PLACE:  self._tune_global_place,
            FlowStage.DETAIL_PLACE:  self._tune_detail_place,
            FlowStage.CTS:           self._tune_cts,
            FlowStage.GLOBAL_ROUTE:  self._tune_global_route,
            FlowStage.DETAIL_ROUTE:  self._tune_detail_route,
        }
        fn = dispatch.get(stage)
        if fn:
            suggestions = fn(current_metrics, history, iter_n)

        if self.space:
            suggestions = self.space.clip_all(suggestions)

        if suggestions:
            logger.info("[TUNER] %s iter=%d → %s", stage.value, iter_n, suggestions)
        return suggestions

    def _tune_global_place(self, m: dict, h: dict, n: int) -> dict:
        out: dict[str, Any] = {}
        overflow = float(m.get("overflow", 0.0))
        if overflow > 20.0:
            out["target_density"] = max(0.50, 0.70 - 0.05 * n)
            out["routability_driven"] = True
        elif overflow < 5.0:
            out["target_density"] = min(0.80, 0.70 + 0.02)
        wns = float(m.get("wns", 0.0))
        if wns < -1.0:
            out["timing_driven"] = True
            out["repair_before_dp"] = True
        return out

    def _tune_detail_place(self, m: dict, h: dict, n: int) -> dict:
        out: dict[str, Any] = {}
        wns = float(m.get("wns", 0.0))
        if wns < -0.5:
            out["repair_timing"] = True
            out["slack_margin"] = 0.05
            out["max_buffer_percent"] = min(30, 20 + 5 * n)
        return out

    def _tune_cts(self, m: dict, h: dict, n: int) -> dict:
        out: dict[str, Any] = {}
        skew = float(m.get("skew_ps", 0.0))
        if skew > 300.0:
            out["cts_cluster_size"] = max(10, 20 - 2 * n)
            out["cts_buf_distance"] = max(50, 100 - 10 * n)
        wns = float(m.get("wns", 0.0))
        if wns < -0.5:
            out["repair_post_cts"] = True
            out["post_cts_slack_margin"] = 0.1
        return out

    def _tune_global_route(self, m: dict, h: dict, n: int) -> dict:
        out: dict[str, Any] = {}
        overflow = float(m.get("overflow", 0.0))
        if overflow > 10.0:
            out["routing_overflow_iter"] = 50 + 25 * n
            out["allow_congestion"] = overflow > 30.0
        wns = float(m.get("wns", 0.0))
        if wns < -0.3:
            out["repair_post_groute"] = True
        return out

    def _tune_detail_route(self, m: dict, h: dict, n: int) -> dict:
        out: dict[str, Any] = {}
        drc = float(m.get("drc_violations", 0.0))
        if drc > 0:
            out["droute_end_iter"] = min(256, 64 + 32 * n)
        return out
