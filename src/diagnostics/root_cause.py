from __future__ import annotations
from typing import Any

from ..core.state_model import DesignState, FlowStage
from .failure_classifier import FailureClassifier, FailureClass


_ROOT_CAUSE_TEMPLATES: dict[FailureClass, str] = {
    FailureClass.FLOORPLAN_INFEASIBLE: (
        "Root cause: The die or core area is too small to accommodate the design.\n"
        "Evidence: cell count vs. site rows, utilization estimate.\n"
        "The floorplan dimensions must be increased or the design must be optimized."
    ),
    FailureClass.MACRO_CONGESTION: (
        "Root cause: Hard macro placement is causing routing blockages.\n"
        "Evidence: overflow hotspots near macro boundaries.\n"
        "Macro halos/spacers should be increased, or macros repositioned."
    ),
    FailureClass.PLACEMENT_OVERFLOW: (
        "Root cause: Global placement did not converge — placement overflow is too high.\n"
        "Evidence: RUDY overflow metric exceeds 20%%.\n"
        "Reduce target density or increase die area. Check macro blockages."
    ),
    FailureClass.TIMING_DIVERGENCE_CTS: (
        "Root cause: Clock tree synthesis cannot meet skew/timing constraints.\n"
        "Evidence: Clock skew > 500 ps or WNS worsened after CTS.\n"
        "Relax clock constraints, add buffers to the list, or increase cluster spacing."
    ),
    FailureClass.ROUTING_OVERFLOW: (
        "Root cause: Global routing has unresolvable congestion.\n"
        "Evidence: Post-routing overflow > 5%%, unrouted nets remain.\n"
        "Increase routing iterations or reduce design density before routing."
    ),
    FailureClass.ROUTING_DRC: (
        "Root cause: Detailed routing produced design-rule violations.\n"
        "Evidence: DRC violation count > 0 in droute output.\n"
        "Increase droute end-iteration limit. Check layer spacing rules."
    ),
    FailureClass.ANTENNA_VIOLATION: (
        "Root cause: Long metal wires accumulate charge violating antenna rules.\n"
        "Evidence: Antenna ratio violations in DRC report.\n"
        "Enable antenna fix pass or insert antenna diodes."
    ),
    FailureClass.SYNTHESIS_MISSING: (
        "Root cause: Synthesis output files (netlist, SDC) are missing or corrupt.\n"
        "Evidence: File-not-found error during synthesis handoff.\n"
        "Re-run synthesis or check synthesis flow output paths."
    ),
    FailureClass.TOOL_CRASH: (
        "Root cause: The EDA tool crashed unexpectedly.\n"
        "Evidence: Segmentation fault / core dump in the log.\n"
        "Check for unsupported PDK features, corrupt database, or memory limits."
    ),
    FailureClass.TIMEOUT: (
        "Root cause: The stage exceeded the configured wall-clock limit.\n"
        "Evidence: Process killed / timeout in log.\n"
        "Increase timeout, reduce design complexity, or check for hangs."
    ),
    FailureClass.UNKNOWN: (
        "Root cause: Failure could not be automatically classified.\n"
        "Manual inspection of the stage log is required."
    ),
}


class RootCauseAnalyzer:
    def __init__(self):
        self._classifier = FailureClassifier()

    def analyze(
        self,
        stage: FlowStage,
        error_msg: str,
        state: DesignState,
    ) -> str:
        metrics = state.record(stage).metrics
        fc = self._classifier.classify(error_msg, metrics)
        conf = self._classifier.confidence(error_msg)
        template = _ROOT_CAUSE_TEMPLATES.get(fc, _ROOT_CAUSE_TEMPLATES[FailureClass.UNKNOWN])

        metric_lines = "\n".join(
            f"  {k}: {v}" for k, v in (metrics or {}).items()
        )

        history_lines = []
        for s in FlowStage.ordered():
            rec = state.record(s)
            if rec.metrics:
                wns = rec.metrics.get("wns", "N/A")
                overflow = rec.metrics.get("overflow", "N/A")
                history_lines.append(f"  {s.value}: wns={wns} overflow={overflow}")

        return (
            f"=== Failure Diagnosis ===\n"
            f"Design : {state.design_name}\n"
            f"Stage  : {stage.value}\n"
            f"Class  : {fc.value}  (confidence={conf:.0%})\n\n"
            f"{template}\n\n"
            f"--- Last Stage Metrics ---\n{metric_lines or '  (none)'}\n\n"
            f"--- QoR History (wns / overflow) ---\n"
            + "\n".join(history_lines or ["  (none)"])
            + "\n"
        )
