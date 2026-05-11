from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

from ..core.state_model import FlowStage

logger = logging.getLogger(__name__)


class ExperimentSummary:
    """
    Aggregates results from one or many runs into structured summary tables
    used by both the markdown reporter and README updater.
    """

    def __init__(self, runs_dir: Path):
        self.runs_dir = Path(runs_dir)
        self._summaries: list[dict[str, Any]] = []

    def load_all(self) -> None:
        self._summaries.clear()
        for f in sorted(self.runs_dir.glob("**/*_summary.json")):
            try:
                data = json.loads(f.read_text())
                self._summaries.append(data)
            except Exception as exc:
                logger.warning("Could not load summary %s: %s", f, exc)
        logger.info("Loaded %d run summaries", len(self._summaries))

    def flat_rows(self) -> list[dict[str, Any]]:
        rows = []
        for s in self._summaries:
            row: dict[str, Any] = {
                "run_id": s.get("run_id", ""),
                "design": s.get("design", ""),
                "seed": s.get("seed", ""),
                "is_complete": s.get("is_complete", False),
                "total_runtime_s": s.get("total_runtime_s", 0),
            }
            for stage, sr in s.get("stages", {}).items():
                metrics = sr.get("metrics", {})
                for k, v in metrics.items():
                    row[f"{stage}_{k}"] = v
                row[f"{stage}_runtime_s"] = sr.get("runtime_s", 0)
                row[f"{stage}_status"] = sr.get("status", "")
                row[f"{stage}_retries"] = sr.get("retries", 0)
            row.update({
                "wns": self._last_metric(s, "wns"),
                "tns": self._last_metric(s, "tns"),
                "overflow": self._last_metric(s, "overflow"),
                "drc_violations": self._last_metric(s, "drc_violations"),
                "wirelength": self._last_metric(s, "wirelength"),
                "utilization": self._last_metric(s, "utilization"),
            })
            rows.append(row)
        return rows

    def _last_metric(self, summary: dict, key: str) -> Any:
        for stage in reversed(FlowStage.ordered()):
            sr = summary.get("stages", {}).get(stage.value, {})
            val = sr.get("metrics", {}).get(key)
            if val is not None:
                return val
        return "N/A"

    def success_rate_by_design(self) -> dict[str, float]:
        from collections import defaultdict
        counts: dict[str, list[bool]] = defaultdict(list)
        for s in self._summaries:
            design = s.get("design", "unknown")
            counts[design].append(bool(s.get("is_complete")))
        return {d: sum(v) / len(v) for d, v in counts.items()}

    def best_run(self, design: str, metric: str = "wns") -> dict[str, Any] | None:
        candidates = [s for s in self._summaries if s.get("design") == design]
        if not candidates:
            return None
        def _score(s: dict) -> float:
            v = self._last_metric(s, metric)
            try:
                return float(v)
            except (TypeError, ValueError):
                return -1e9
        return max(candidates, key=_score)

    def ablation_table(
        self,
        config_key: str = "config_tag",
        metrics: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        metrics = metrics or ["wns", "tns", "overflow", "drc_violations"]
        groups: dict[str, list[dict]] = {}
        for s in self._summaries:
            tag = s.get(config_key, "default")
            groups.setdefault(tag, []).append(s)
        rows = []
        for tag, runs in groups.items():
            row: dict[str, Any] = {"config": tag, "n_runs": len(runs)}
            for m in metrics:
                vals = [self._last_metric(r, m) for r in runs]
                nums = [float(v) for v in vals if isinstance(v, (int, float))]
                row[f"{m}_mean"] = round(sum(nums) / len(nums), 4) if nums else "N/A"
            rows.append(row)
        return rows
