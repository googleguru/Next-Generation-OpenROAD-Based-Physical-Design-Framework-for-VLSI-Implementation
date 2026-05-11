from __future__ import annotations
import logging
from pathlib import Path
from typing import Any

from .plot_engine import PlotEngine, PALETTE

logger = logging.getLogger(__name__)


class ComparisonPlotter:
    """
    Ablation study, multi-seed, and cross-benchmark comparison charts.
    """

    def __init__(self, output_dir: Path):
        self.engine = PlotEngine(output_dir)

    def plot_ablation(
        self,
        ablation_data: dict[str, dict[str, float]],
        metrics: list[str],
        save_name: str = "ablation",
    ) -> Path | None:
        try:
            import matplotlib.pyplot as plt
            import numpy as np
        except ImportError:
            return None

        configs = list(ablation_data.keys())
        n_metrics = len(metrics)
        fig, axes = self.engine.new_figure(
            nrows=1, ncols=n_metrics,
            figsize=(4 * n_metrics, 5),
        )
        if fig is None:
            return None
        if n_metrics == 1:
            axes = [axes]

        for ax, metric in zip(axes, metrics):
            vals = [ablation_data[c].get(metric, 0) for c in configs]
            colors = PALETTE[:len(configs)]
            bars = ax.bar(configs, vals, color=colors, width=0.6, zorder=3)
            self.engine.annotate_bars(ax, fmt="{:.2f}")
            ax.set_title(metric, fontsize=10)
            ax.set_ylabel(metric, fontsize=9)
            self.engine.rotate_xlabels(ax, rotation=35)

        fig.suptitle("Ablation Study: Module Contribution", y=1.02, fontsize=13)
        return self.engine.save(fig, save_name)

    def plot_benchmark_summary_table(
        self,
        results: list[dict[str, Any]],
        columns: list[str],
        save_name: str = "benchmark_summary",
    ) -> Path | None:
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            return None

        designs = [r.get("design", f"#{i}") for i, r in enumerate(results)]
        data = [[str(round(r.get(c, "N/A"), 3))
                  if isinstance(r.get(c), float) else str(r.get(c, "N/A"))
                  for c in columns]
                 for r in results]

        fig, ax = self.engine.new_figure(
            figsize=(max(8, len(columns) * 1.5), max(3, len(designs) * 0.5))
        )
        if fig is None:
            return None
        ax.axis("off")
        tbl = ax.table(
            cellText=data,
            rowLabels=designs,
            colLabels=columns,
            cellLoc="center",
            loc="center",
        )
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(9)
        tbl.scale(1.2, 1.4)
        for (row, col), cell in tbl.get_celld().items():
            if row == 0:
                cell.set_facecolor("#1565C0")
                cell.set_text_props(color="white", weight="bold")
            elif row % 2 == 0:
                cell.set_facecolor("#E3F2FD")
        ax.set_title("Benchmark Results Summary", fontsize=13, pad=16)
        return self.engine.save(fig, save_name)

    def plot_multi_seed_box(
        self,
        seed_data: dict[str, list[float]],
        metric: str,
        save_name: str = "multi_seed_box",
    ) -> Path | None:
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            return None

        designs = list(seed_data.keys())
        values = [seed_data[d] for d in designs]
        fig, ax = self.engine.new_figure(figsize=(max(6, len(designs) * 1.5), 5))
        if fig is None:
            return None
        bp = ax.boxplot(values, labels=designs, patch_artist=True,
                         medianprops=dict(color="red", linewidth=2))
        for patch, color in zip(bp["boxes"], PALETTE):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        self.engine.rotate_xlabels(ax, rotation=25)
        ax.set_ylabel(metric)
        ax.set_title(f"Multi-Seed Distribution: {metric}", pad=10)
        return self.engine.save(fig, save_name)

    def plot_success_rate(
        self,
        success_data: dict[str, float],
        save_name: str = "success_rate",
    ) -> Path | None:
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            return None

        designs = list(success_data.keys())
        rates = [success_data[d] * 100 for d in designs]
        fig, ax = self.engine.new_figure(figsize=(max(6, len(designs) * 1.0), 4))
        if fig is None:
            return None
        colors = ["#4CAF50" if r >= 80 else "#FF9800" if r >= 50 else "#F44336"
                   for r in rates]
        ax.bar(designs, rates, color=colors, width=0.6, zorder=3)
        ax.axhline(80, color="green", linewidth=1, linestyle="--",
                    alpha=0.7, label="80% target")
        ax.set_ylim(0, 110)
        ax.set_ylabel("Success Rate (%)")
        ax.set_title("Flow Success Rate by Design", pad=10)
        ax.legend(loc="lower right")
        self.engine.annotate_bars(ax, fmt="{:.0f}%")
        self.engine.rotate_xlabels(ax)
        return self.engine.save(fig, save_name)
