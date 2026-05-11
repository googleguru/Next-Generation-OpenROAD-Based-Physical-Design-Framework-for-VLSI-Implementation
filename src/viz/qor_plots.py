from __future__ import annotations
import logging
from pathlib import Path
from typing import Any

from .plot_engine import PlotEngine, PALETTE

logger = logging.getLogger(__name__)


class QoRPlotter:
    """
    Publication-ready QoR trend and per-stage breakdown plots.
    All figures use white backgrounds with no overlapping content.
    """

    def __init__(self, output_dir: Path):
        self.engine = PlotEngine(output_dir)

    def plot_qor_trend(
        self,
        trend_data: list[tuple[str, float]],
        metric: str,
        title: str = "",
        save_name: str = "qor_trend",
    ) -> Path | None:
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            logger.warning("matplotlib not available")
            return None

        stages = [t[0] for t in trend_data]
        values = [t[1] for t in trend_data]
        fig, ax = self.engine.new_figure(figsize=(8, 4))
        if fig is None:
            return None
        ax.plot(stages, values, marker="o", color=PALETTE[0],
                linewidth=2, markersize=7, zorder=3)
        ax.fill_between(range(len(stages)), values,
                         alpha=0.12, color=PALETTE[0])
        for i, (s, v) in enumerate(zip(stages, values)):
            ax.annotate(
                f"{v:.3f}", xy=(i, v), xytext=(0, 8),
                textcoords="offset points",
                ha="center", fontsize=8, color="#333",
            )
        ax.set_xticks(range(len(stages)))
        ax.set_xticklabels(stages, rotation=25, ha="right")
        ax.set_ylabel(metric)
        ax.set_xlabel("Flow Stage")
        ax.set_title(title or f"QoR Trend: {metric}", pad=10)
        ax.axhline(0, color="red", linewidth=0.8, linestyle="--", alpha=0.5)
        return self.engine.save(fig, save_name)

    def plot_stage_runtime(
        self,
        runtime_data: list[tuple[str, float]],
        save_name: str = "runtime_breakdown",
    ) -> Path | None:
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            return None

        stages = [r[0] for r in runtime_data]
        runtimes = [r[1] for r in runtime_data]
        fig, ax = self.engine.new_figure(figsize=(9, 4))
        if fig is None:
            return None
        bars = ax.bar(stages, runtimes, color=PALETTE[:len(stages)],
                       width=0.6, zorder=3)
        self.engine.annotate_bars(ax, fmt="{:.1f}s")
        self.engine.rotate_xlabels(ax)
        ax.set_ylabel("Runtime (s)")
        ax.set_title("Per-Stage Runtime Breakdown", pad=10)
        return self.engine.save(fig, save_name)

    def plot_multi_metric(
        self,
        stage_metrics: dict[str, dict[str, Any]],
        metrics: list[str],
        save_name: str = "multi_metric",
    ) -> Path | None:
        try:
            import matplotlib.pyplot as plt
            import numpy as np
        except ImportError:
            return None

        valid_metrics = [m for m in metrics
                          if any(m in v for v in stage_metrics.values())]
        if not valid_metrics:
            return None

        stages = list(stage_metrics.keys())
        n_metrics = len(valid_metrics)
        fig, axes = self.engine.new_figure(
            nrows=n_metrics, ncols=1,
            figsize=(9, 3 * n_metrics),
        )
        if fig is None:
            return None
        if n_metrics == 1:
            axes = [axes]
        for ax, metric in zip(axes, valid_metrics):
            vals = [float(stage_metrics[s].get(metric, 0) or 0) for s in stages]
            ax.plot(stages, vals, marker="s", color=PALETTE[
                valid_metrics.index(metric) % len(PALETTE)
            ], linewidth=2, markersize=6)
            ax.set_ylabel(metric, fontsize=9)
            ax.set_xticks(range(len(stages)))
            ax.set_xticklabels(stages, rotation=20, ha="right", fontsize=8)
        axes[0].set_title("Cross-Stage QoR Metrics", pad=10)
        return self.engine.save(fig, save_name)

    def plot_wns_tns_bars(
        self,
        runs: list[dict[str, Any]],
        save_name: str = "wns_tns_comparison",
    ) -> Path | None:
        try:
            import matplotlib.pyplot as plt
            import numpy as np
        except ImportError:
            return None

        designs = [r.get("design", f"run_{i}") for i, r in enumerate(runs)]
        wns_vals = [float(r.get("wns", 0) or 0) for r in runs]
        tns_vals = [float(r.get("tns", 0) or 0) for r in runs]

        x = np.arange(len(designs))
        width = 0.35
        fig, ax = self.engine.new_figure(figsize=(max(8, len(designs) * 1.2), 5))
        if fig is None:
            return None
        ax.bar(x - width / 2, wns_vals, width, label="WNS (ns)",
               color=PALETTE[0], alpha=0.85)
        ax.bar(x + width / 2, tns_vals, width, label="TNS (ns)",
               color=PALETTE[1], alpha=0.85)
        ax.set_xticks(x)
        ax.set_xticklabels(designs, rotation=25, ha="right")
        ax.set_ylabel("Slack (ns)")
        ax.set_title("WNS / TNS Comparison Across Designs", pad=10)
        ax.legend(loc="lower right", bbox_to_anchor=(1, 0))
        ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
        return self.engine.save(fig, save_name)
