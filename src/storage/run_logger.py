from __future__ import annotations
import csv
import json
import logging
from pathlib import Path
from typing import Any

from ..core.state_model import DesignState, FlowStage

logger = logging.getLogger(__name__)


class RunLogger:
    """
    Persists experiment results in CSV, JSON, and structured log formats.
    Supports checkpointing mid-flow and final aggregated outputs.
    """

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._run_rows: list[dict[str, Any]] = []

    def checkpoint(self, state: DesignState, stage: FlowStage) -> None:
        rec = state.record(stage)
        row = {
            "run_id": state.run_id,
            "design": state.design_name,
            "seed": state.seed,
            "stage": stage.value,
            "status": rec.status.value,
            "runtime_s": round(rec.runtime_s, 2),
            "retries": rec.retry_count,
        }
        row.update({f"m_{k}": v for k, v in rec.metrics.items()})
        self._run_rows.append(row)
        self._flush_csv()

    def save(self, state: DesignState) -> None:
        summary = {
            "run_id": state.run_id,
            "design": state.design_name,
            "seed": state.seed,
            "is_complete": state.is_flow_complete(),
            "total_runtime_s": round(state.total_runtime(), 2),
            "stages": {
                s.value: {
                    "status": r.status.value,
                    "runtime_s": round(r.runtime_s, 2),
                    "retries": r.retry_count,
                    "metrics": r.metrics,
                    "error": r.error_msg,
                }
                for s, r in state.stage_records.items()
            },
        }
        out = self.output_dir / f"{state.run_id}_summary.json"
        out.write_text(json.dumps(summary, indent=2, default=str))
        logger.info("Run summary saved: %s", out)

    def _flush_csv(self) -> None:
        if not self._run_rows:
            return
        csv_path = self.output_dir / "runs.csv"
        fieldnames = sorted(
            {k for row in self._run_rows for k in row.keys()}
        )
        with open(csv_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames,
                                     extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self._run_rows)

    def load_csv(self) -> list[dict[str, Any]]:
        csv_path = self.output_dir / "runs.csv"
        if not csv_path.exists():
            return []
        with open(csv_path) as fh:
            return list(csv.DictReader(fh))

    def aggregate_parquet(self, dest: Path) -> None:
        try:
            import pandas as pd
            rows = self.load_csv()
            if rows:
                df = pd.DataFrame(rows)
                df.to_parquet(dest, index=False)
                logger.info("Aggregated parquet saved: %s", dest)
        except ImportError:
            logger.warning("pandas not installed — skipping parquet export")
