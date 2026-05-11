from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MetricSpec:
    name: str
    unit: str
    better: str          # "lower" | "higher"
    critical: bool = False
    alarm_threshold: Optional[float] = None
    description: str = ""


METRIC_REGISTRY: dict[str, MetricSpec] = {
    "wns": MetricSpec("wns", "ns", "higher", critical=True,
                      alarm_threshold=-0.5,
                      description="Worst Negative Slack (setup)"),
    "tns": MetricSpec("tns", "ns", "higher", critical=True,
                      alarm_threshold=-100.0,
                      description="Total Negative Slack (setup)"),
    "hold_wns": MetricSpec("hold_wns", "ns", "higher", critical=False,
                            alarm_threshold=-0.1),
    "setup_violations": MetricSpec("setup_violations", "#", "lower",
                                    critical=True, alarm_threshold=0),
    "hold_violations": MetricSpec("hold_violations", "#", "lower",
                                   critical=False, alarm_threshold=0),
    "overflow": MetricSpec("overflow", "%", "lower", critical=True,
                            alarm_threshold=10.0,
                            description="Placement overflow (RUDY proxy)"),
    "hpwl": MetricSpec("hpwl", "um", "lower",
                        description="Half-Perimeter Wire Length estimate"),
    "wirelength": MetricSpec("wirelength", "um", "lower",
                              description="Routed total wire length"),
    "utilization": MetricSpec("utilization", "%", "lower",
                               alarm_threshold=85.0),
    "drc_violations": MetricSpec("drc_violations", "#", "lower",
                                  critical=True, alarm_threshold=0,
                                  description="DRC rule violations"),
    "antenna_violations": MetricSpec("antenna_violations", "#", "lower",
                                      alarm_threshold=0),
    "skew_ps": MetricSpec("skew_ps", "ps", "lower",
                           alarm_threshold=200.0,
                           description="Clock skew (ps)"),
    "power_mw": MetricSpec("power_mw", "mW", "lower",
                            description="Estimated total power"),
    "num_buffers": MetricSpec("num_buffers", "#", "lower",
                               description="Repair buffers inserted"),
    "routing_iterations": MetricSpec("routing_iterations", "#", "lower"),
    "runtime_s": MetricSpec("runtime_s", "s", "lower"),
    "core_area": MetricSpec("core_area", "um^2", "lower"),
}


@dataclass
class QoRMetrics:
    stage: str
    values: dict[str, Any] = field(default_factory=dict)

    def get(self, name: str, default: Any = None) -> Any:
        return self.values.get(name, default)

    def is_alarm(self, name: str) -> bool:
        spec = METRIC_REGISTRY.get(name)
        val = self.values.get(name)
        if spec is None or val is None or spec.alarm_threshold is None:
            return False
        if spec.better == "lower":
            return float(val) > spec.alarm_threshold
        return float(val) < spec.alarm_threshold

    def alarms(self) -> list[str]:
        return [name for name in self.values if self.is_alarm(name)]

    def critical_alarms(self) -> list[str]:
        return [
            name for name in self.alarms()
            if METRIC_REGISTRY.get(name, MetricSpec("", "", "")).critical
        ]

    def delta(self, other: "QoRMetrics") -> dict[str, float]:
        result: dict[str, float] = {}
        for key in self.values:
            if key in other.values:
                try:
                    result[key] = float(self.values[key]) - float(other.values[key])
                except (TypeError, ValueError):
                    pass
        return result

    def to_flat_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, **self.values}
