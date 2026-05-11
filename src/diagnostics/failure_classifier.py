from __future__ import annotations
import re
from enum import Enum
from typing import Any


class FailureClass(str, Enum):
    FLOORPLAN_INFEASIBLE    = "floorplan_infeasible"
    MACRO_CONGESTION        = "macro_congestion"
    PLACEMENT_OVERFLOW      = "placement_overflow"
    TIMING_DIVERGENCE_CTS   = "timing_divergence_cts"
    ROUTING_OVERFLOW        = "routing_overflow"
    ROUTING_DRC             = "routing_drc"
    ANTENNA_VIOLATION       = "antenna_violation"
    SYNTHESIS_MISSING       = "synthesis_missing"
    TOOL_CRASH              = "tool_crash"
    TIMEOUT                 = "timeout"
    UNKNOWN                 = "unknown"


_PATTERN_MAP: list[tuple[str, FailureClass]] = [
    (r"cannot fit|infeasible|die area too small", FailureClass.FLOORPLAN_INFEASIBLE),
    (r"macro.*overlap|macro.*congestion", FailureClass.MACRO_CONGESTION),
    (r"overflow.*stagnate|overflow > [3-9]\d|overflow = 1\d\d", FailureClass.PLACEMENT_OVERFLOW),
    (r"cts.*diverge|clock.*timing.*fail|skew.*exceed", FailureClass.TIMING_DIVERGENCE_CTS),
    (r"routing overflow|unrouted.*net|cannot route", FailureClass.ROUTING_OVERFLOW),
    (r"drc.*fail|design rule violation|short.*violation", FailureClass.ROUTING_DRC),
    (r"antenna.*violation|antenna.*ratio", FailureClass.ANTENNA_VIOLATION),
    (r"netlist not found|sdc not found|synthesis.*missing", FailureClass.SYNTHESIS_MISSING),
    (r"segmentation fault|abort|core dump|exception", FailureClass.TOOL_CRASH),
    (r"timed out|timeout|killed", FailureClass.TIMEOUT),
]


class FailureClassifier:
    def classify(
        self,
        error_msg: str,
        metrics: dict[str, Any] | None = None,
    ) -> FailureClass:
        lower = error_msg.lower()
        for pattern, fc in _PATTERN_MAP:
            if re.search(pattern, lower):
                return fc

        if metrics:
            overflow = float(metrics.get("overflow", 0.0))
            drc = float(metrics.get("drc_violations", 0.0))
            skew = float(metrics.get("skew_ps", 0.0))
            if overflow > 30.0:
                return FailureClass.PLACEMENT_OVERFLOW
            if drc > 0:
                return FailureClass.ROUTING_DRC
            if skew > 500.0:
                return FailureClass.TIMING_DIVERGENCE_CTS

        return FailureClass.UNKNOWN

    def confidence(self, error_msg: str) -> float:
        lower = error_msg.lower()
        for pattern, _ in _PATTERN_MAP:
            if re.search(pattern, lower):
                return 0.85
        return 0.30
