from __future__ import annotations
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..core.state_model import FlowStage

logger = logging.getLogger(__name__)


class RollbackDecision(str, Enum):
    PROCEED = "proceed"
    RETRY_CURRENT = "retry_current"
    ROLLBACK_ONE = "rollback_one"
    ROLLBACK_TWO = "rollback_two"
    ABORT = "abort"


@dataclass
class RollbackRule:
    metric: str
    threshold: float
    comparison: str   # "gt" | "lt"
    decision: RollbackDecision
    message: str = ""


class RollbackPolicy:
    """
    Evaluates post-stage metrics against configured thresholds and
    recommends rollback, retry, or proceed decisions.
    """

    _DEFAULT_RULES: list[RollbackRule] = [
        RollbackRule("overflow",       40.0, "gt", RollbackDecision.ROLLBACK_ONE,
                     "Placement overflow too high — roll back to global placement"),
        RollbackRule("wns",           -2.0,  "lt", RollbackDecision.RETRY_CURRENT,
                     "Severe setup timing violation — retry with relaxed params"),
        RollbackRule("drc_violations", 500,  "gt", RollbackDecision.ROLLBACK_ONE,
                     "Too many DRC violations — roll back to global routing"),
        RollbackRule("drc_violations", 5000, "gt", RollbackDecision.ROLLBACK_TWO,
                     "DRC unrecoverable — roll back to CTS"),
        RollbackRule("skew_ps",        500,  "gt", RollbackDecision.RETRY_CURRENT,
                     "Excessive clock skew — retry CTS with larger buffer list"),
    ]

    def __init__(self, rules: list[RollbackRule] | None = None):
        self.rules = rules if rules is not None else list(self._DEFAULT_RULES)

    def evaluate(
        self,
        stage: FlowStage,
        metrics: dict[str, Any],
        retry_count: int = 0,
        max_retries: int = 2,
    ) -> RollbackDecision:
        for rule in self.rules:
            val = metrics.get(rule.metric)
            if val is None:
                continue
            try:
                val = float(val)
            except (TypeError, ValueError):
                continue
            triggered = (
                (rule.comparison == "gt" and val > rule.threshold) or
                (rule.comparison == "lt" and val < rule.threshold)
            )
            if triggered:
                if retry_count >= max_retries:
                    decision = RollbackDecision.ABORT
                else:
                    decision = rule.decision
                logger.info(
                    "[ROLLBACK] stage=%s metric=%s val=%.3f → %s  (%s)",
                    stage.value, rule.metric, val, decision.value, rule.message
                )
                return decision
        return RollbackDecision.PROCEED

    def apply_rollback_params(
        self,
        stage: FlowStage,
        decision: RollbackDecision,
        current_params: dict[str, Any],
    ) -> dict[str, Any]:
        params = dict(current_params)
        if decision == RollbackDecision.RETRY_CURRENT:
            if stage == FlowStage.GLOBAL_PLACE:
                params["target_density"] = max(
                    0.50, float(params.get("target_density", 0.70)) - 0.05
                )
            elif stage == FlowStage.CTS:
                params["cts_buf_list"] = params.get(
                    "cts_buf_list", "BUF_X2 BUF_X4 BUF_X8"
                ) + " BUF_X16"
            elif stage == FlowStage.DETAIL_ROUTE:
                params["droute_end_iter"] = min(
                    256, int(params.get("droute_end_iter", 64)) + 32
                )
        return params
