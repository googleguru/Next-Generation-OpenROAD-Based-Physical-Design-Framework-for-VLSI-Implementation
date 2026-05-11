from __future__ import annotations
import re
import logging
from pathlib import Path
from typing import Any

from ..core.state_model import FlowStage

logger = logging.getLogger(__name__)

_FLOAT = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"


class MetricsExtractor:
    """
    Parses stage output files (logs, reports, DEF/ODB summaries) and
    returns a flat dict of numeric/string metrics.
    """

    _PATTERNS: dict[str, str] = {
        "wns":              r"(?:WNS|wns)\s*[=:]\s*(" + _FLOAT + r")",
        "tns":              r"(?:TNS|tns)\s*[=:]\s*(" + _FLOAT + r")",
        "setup_violations": r"(?:Setup|setup)\s+violations?\s*[=:]\s*(\d+)",
        "hold_violations":  r"(?:Hold|hold)\s+violations?\s*[=:]\s*(\d+)",
        "overflow":         r"(?:overflow|OF)\s*[=:]\s*(" + _FLOAT + r")",
        "hpwl":             r"(?:HPWL|hpwl)\s*[=:]\s*(" + _FLOAT + r")",
        "utilization":      r"(?:Utilization|utilization)\s*[=:]\s*(" + _FLOAT + r")\s*%?",
        "core_area":        r"(?:Core area|core_area)\s*[=:]\s*(" + _FLOAT + r")",
        "die_area":         r"(?:Die area|die_area)\s*[=:]\s*(" + _FLOAT + r")",
        "drc_violations":   r"(?:DRC violations?|drc_violations?)\s*[=:]\s*(\d+)",
        "antenna_violations": r"(?:Antenna violations?)\s*[=:]\s*(\d+)",
        "wirelength":       r"(?:Total wire length|wirelength)\s*[=:]\s*(" + _FLOAT + r")",
        "clock_period_ns":  r"(?:Clock period|clock period)\s*[=:]\s*(" + _FLOAT + r")\s*ns",
        "skew_ps":          r"(?:Skew|skew)\s*[=:]\s*(" + _FLOAT + r")\s*ps",
        "power_mw":         r"(?:Total power|total power)\s*[=:]\s*(" + _FLOAT + r")\s*mW",
        "num_buffers":      r"(?:Buffers inserted|buffers)\s*[=:]\s*(\d+)",
        "num_repeaters":    r"(?:Repeaters|repeaters)\s*[=:]\s*(\d+)",
        "routing_iterations": r"(?:Routing iterations?)\s*[=:]\s*(\d+)",
    }

    _STAGE_REPORTS: dict[FlowStage, list[str]] = {
        FlowStage.FLOORPLAN:    ["floorplan.log", "stage.log"],
        FlowStage.PDN:          ["pdn.log", "stage.log"],
        FlowStage.GLOBAL_PLACE: ["gplace.log", "stage.log"],
        FlowStage.DETAIL_PLACE: ["dplace.log", "stage.log"],
        FlowStage.CTS:          ["cts.log", "stage.log"],
        FlowStage.GLOBAL_ROUTE: ["groute.log", "stage.log"],
        FlowStage.DETAIL_ROUTE: ["droute.log", "stage.log"],
        FlowStage.FINISH:       ["finish.log", "stage.log",
                                  "final_timing.rpt", "final_drc.rpt"],
    }

    def extract(
        self,
        stage: FlowStage,
        work_dir: Path,
        log_path: Path | None = None,
    ) -> dict[str, Any]:
        metrics: dict[str, Any] = {}
        search_files: list[Path] = []

        if log_path and log_path.exists():
            search_files.append(log_path)

        for fname in self._STAGE_REPORTS.get(stage, []):
            p = work_dir / fname
            if p.exists() and p not in search_files:
                search_files.append(p)

        combined = ""
        for fp in search_files:
            try:
                combined += fp.read_text(errors="replace") + "\n"
            except OSError:
                pass

        for key, pattern in self._PATTERNS.items():
            match = re.search(pattern, combined, re.IGNORECASE)
            if match:
                raw = match.group(1)
                try:
                    metrics[key] = float(raw)
                except ValueError:
                    metrics[key] = raw

        metrics["stage"] = stage.value
        metrics["log_size_bytes"] = sum(
            fp.stat().st_size for fp in search_files if fp.exists()
        )
        self._add_stage_specifics(stage, work_dir, metrics)
        return metrics

    def _add_stage_specifics(
        self, stage: FlowStage, work_dir: Path, metrics: dict[str, Any]
    ) -> None:
        if stage == FlowStage.GLOBAL_PLACE:
            metrics.setdefault("overflow", _parse_gplace_overflow(work_dir))
        elif stage == FlowStage.DETAIL_ROUTE:
            metrics.setdefault("drc_violations", _parse_drc_count(work_dir))
        elif stage == FlowStage.FINISH:
            timing = _parse_finish_timing(work_dir)
            metrics.update(timing)


def _parse_gplace_overflow(work_dir: Path) -> float:
    log = work_dir / "stage.log"
    if not log.exists():
        return -1.0
    text = log.read_text(errors="replace")
    matches = re.findall(r"Overflow\s*[:=]\s*(" + _FLOAT + r")", text, re.I)
    if matches:
        return float(matches[-1])
    return -1.0


def _parse_drc_count(work_dir: Path) -> int:
    for name in ("final_drc.rpt", "droute.log", "stage.log"):
        p = work_dir / name
        if p.exists():
            text = p.read_text(errors="replace")
            m = re.search(r"Total\s+(?:DRC\s+)?violations?\s*[:=]\s*(\d+)",
                          text, re.I)
            if m:
                return int(m.group(1))
    return -1


def _parse_finish_timing(work_dir: Path) -> dict[str, Any]:
    rpt = work_dir / "final_timing.rpt"
    if not rpt.exists():
        return {}
    text = rpt.read_text(errors="replace")
    out: dict[str, Any] = {}
    for key, pat in [("wns", r"WNS\s*[:=]\s*(" + _FLOAT + r")"),
                     ("tns", r"TNS\s*[:=]\s*(" + _FLOAT + r")"),
                     ("setup_violations", r"Setup violations?\s*[:=]\s*(\d+)")]:
        m = re.search(pat, text, re.I)
        if m:
            try:
                out[key] = float(m.group(1))
            except ValueError:
                out[key] = m.group(1)
    return out
