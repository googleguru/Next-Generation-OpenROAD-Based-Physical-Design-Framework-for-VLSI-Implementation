from __future__ import annotations
from typing import Any

from .failure_classifier import FailureClass

_REMEDIATION_MAP: dict[FailureClass, list[str]] = {
    FailureClass.FLOORPLAN_INFEASIBLE: [
        "Increase die_area_x / die_area_y in the benchmark config by 20-40%.",
        "Reduce synthesis target area by tightening the ABC area map.",
        "Remove unnecessary IO pads or resize the site list.",
    ],
    FailureClass.MACRO_CONGESTION: [
        "Add macro placement halos: increase halo width/height by 5-10 um.",
        "Manually pre-place macros in the benchmark config.",
        "Enable routability-driven placement for surrounding cells.",
    ],
    FailureClass.PLACEMENT_OVERFLOW: [
        "Reduce target_density from 0.70 to 0.65 (or lower).",
        "Enable routability_driven=true in global placement.",
        "Increase die area or remove over-constraining floorplan blockages.",
    ],
    FailureClass.TIMING_DIVERGENCE_CTS: [
        "Expand cts_buf_list to include larger drive-strength buffers (BUF_X16).",
        "Reduce cts_cluster_size from 20 to 10.",
        "Increase clock period constraint (relax target) and re-evaluate.",
    ],
    FailureClass.ROUTING_OVERFLOW: [
        "Increase routing_overflow_iter from 50 to 100.",
        "Reduce placement density further (target_density -= 0.05).",
        "Enable layer assignment relaxation for congested nets.",
    ],
    FailureClass.ROUTING_DRC: [
        "Increase droute_end_iter up to 128 or 256.",
        "Check that all LEF layer rules match the PDK version.",
        "Inspect droute_drc.rpt for rule-type frequency and fix recurring patterns.",
    ],
    FailureClass.ANTENNA_VIOLATION: [
        "Enable fix_antennas=true and increase antenna_fix_iter to 5.",
        "Add antenna diode cells near long wire endpoints.",
        "Verify antenna rule limits in PDK LEF are correctly loaded.",
    ],
    FailureClass.SYNTHESIS_MISSING: [
        "Re-run the synthesis stage: make synth DESIGN=<name>.",
        "Verify synth_netlist and synth_sdc paths in the benchmark config.",
        "Check that Yosys / synthesis tool completed without errors.",
    ],
    FailureClass.TOOL_CRASH: [
        "Check available system memory (ulimit -v).",
        "Verify PDK LEF/Liberty files are not corrupt.",
        "Try running the stage in isolation with verbose logging.",
    ],
    FailureClass.TIMEOUT: [
        "Increase timeout_s in the flow config.",
        "Reduce design complexity or split macro-cell mix.",
        "Profile which sub-step is hanging and apply targeted fixes.",
    ],
    FailureClass.UNKNOWN: [
        "Inspect the stage.log file manually for error keywords.",
        "Run the stage in isolation with -verbose flag.",
        "Check for version mismatches between PDK and tool.",
    ],
}


class RemediationEngine:
    def suggest(self, fc: FailureClass) -> list[str]:
        return _REMEDIATION_MAP.get(fc, _REMEDIATION_MAP[FailureClass.UNKNOWN])

    def format_report(self, fc: FailureClass) -> str:
        steps = self.suggest(fc)
        lines = ["Remediation suggestions:"]
        for i, step in enumerate(steps, 1):
            lines.append(f"  {i}. {step}")
        return "\n".join(lines)


class DiagnosticsModule:
    """Convenience façade that combines classifier + root cause + remediation."""

    def __init__(self):
        from .root_cause import RootCauseAnalyzer
        self._rca = RootCauseAnalyzer()
        self._remediation = RemediationEngine()
        from .failure_classifier import FailureClassifier
        self._classifier = FailureClassifier()

    def classify_and_report(
        self,
        stage: Any,
        error: str,
        state: Any,
    ) -> str:
        rca = self._rca.analyze(stage, error, state)
        fc = self._classifier.classify(error, state.record(stage).metrics)
        remediation = self._remediation.format_report(fc)
        return f"{rca}\n{remediation}\n"
