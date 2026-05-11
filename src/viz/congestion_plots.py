from __future__ import annotations
import logging
from pathlib import Path
from typing import Any

from .plot_engine import PlotEngine, PALETTE

logger = logging.getLogger(__name__)


class CongestionPlotter:
    """Congestion, overflow, and routing correlation visualizations."""

    def __init__(self, output_dir: Path):
        self.engine = PlotEngine(output_dir)

    def plot_overflow_trend(
        self,
        overflow_series: list[tuple[str, float]],
        save_name: str = "overflow_trend",
    ) -> Path | None:
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            return None

        stages = [s[0] for s in overflow_series]
        values = [s[1] for s in overflow_series]
        fig, ax = self.engine.new_figure(figsize=(8, 4))
        if fig is None:
            return None
        ax.bar(stages, values, color=[
            "#F44336" if v > 20 else "#FF9800" if v > 10 else "#4CAF50"
            for v in values
        ], width=0.5, zorder=3)
        ax.axhline(10, color="orange", linewidth=1, linestyle="--",
                    label="Warn threshold (10%)")
        ax.axhline(20, color="red", linewidth=1, linestyle="--",
                    label="Critical threshold (20%)")
        self.engine.annotate_bars(ax, fmt="{:.1f}%")
        self.engine.rotate_xlabels(ax)
        ax.set_ylabel("Overflow (%)")
        ax.set_title("Placement Overflow by Stage", pad=10)
        ax.legend(loc="upper right")
        return self.engine.save(fig, save_name)

    def plot_congestion_vs_timing(
        self,
        runs: list[dict[str, Any]],
        save_name: str = "congestion_vs_timing",
    ) -> Path | None:
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            return None

        overflow = [float(r.get("overflow", 0) or 0) for r in runs]
        wns = [float(r.get("wns", 0) or 0) for r in runs]
        labels = [r.get("design", f"#{i}") for i, r in enumerate(runs)]

        fig, ax = self.engine.new_figure(figsize=(7, 5))
        if fig is None:
            return None
        scatter = ax.scatter(overflow, wns, c=range(len(runs)),
                              cmap="coolwarm", s=80, zorder=3, alpha=0.85)
        for i, label in enumerate(labels):
            ax.annotate(label, (overflow[i], wns[i]),
                         textcoords="offset points", xytext=(5, 3),
                         fontsize=7, color="#333")
        ax.axhline(0, color="black", linewidth=0.8, linestyle="--")
        ax.axvline(20, color="red", linewidth=0.8, linestyle="--", alpha=0.5)
        ax.set_xlabel("Placement Overflow (%)")
        ax.set_ylabel("WNS (ns)")
        ax.set_title("Congestion vs. Setup Timing", pad=10)
        fig.colorbar(scatter, ax=ax, label="Run index")
        return self.engine.save(fig, save_name)

    def plot_routing_iterations(
        self,
        iter_data: list[tuple[str, int]],
        save_name: str = "routing_iterations",
    ) -> Path | None:
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            return None

        designs = [d[0] for d in iter_data]
        iters = [d[1] for d in iter_data]
        fig, ax = self.engine.new_figure(figsize=(max(6, len(designs) * 0.8), 4))
        if fig is None:
            return None
        ax.barh(designs, iters, color=PALETTE[2], alpha=0.85)
        ax.set_xlabel("Routing Iterations")
        ax.set_title("Detailed Routing Iterations per Design", pad=10)
        for i, v in enumerate(iters):
            ax.text(v + 0.5, i, str(v), va="center", fontsize=8)
        return self.engine.save(fig, save_name)
