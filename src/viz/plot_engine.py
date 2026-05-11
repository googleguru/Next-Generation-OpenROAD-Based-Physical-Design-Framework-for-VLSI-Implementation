from __future__ import annotations
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STYLE: dict[str, Any] = {
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "axes.edgecolor": "#333333",
    "axes.grid": True,
    "axes.grid.which": "major",
    "grid.color": "#e0e0e0",
    "grid.linewidth": 0.6,
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "axes.titlesize": 13,
    "axes.labelsize": 11,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 9,
    "legend.framealpha": 0.9,
    "legend.edgecolor": "#cccccc",
    "figure.dpi": 150,
    "savefig.dpi": 200,
    "savefig.facecolor": "white",
    "savefig.bbox": "tight",
    "figure.constrained_layout.use": True,
}

PALETTE = [
    "#2196F3", "#F44336", "#4CAF50", "#FF9800",
    "#9C27B0", "#00BCD4", "#795548", "#607D8B",
]


class PlotEngine:
    """
    Base plotting utilities: always white background, constrained layout,
    no overlapping labels, publication-quality defaults.
    """

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._apply_style()

    def _apply_style(self) -> None:
        try:
            import matplotlib as mpl
            mpl.rcParams.update(STYLE)
        except ImportError:
            logger.warning("matplotlib not installed — plots unavailable")

    def save(self, fig: Any, name: str, fmt: str = "png") -> Path | None:
        try:
            import matplotlib.pyplot as plt
            path = self.output_dir / f"{name}.{fmt}"
            fig.savefig(path, facecolor="white")
            plt.close(fig)
            logger.info("Figure saved: %s", path)
            return path
        except Exception as exc:
            logger.error("Failed to save figure %s: %s", name, exc)
            return None

    def new_figure(self, nrows: int = 1, ncols: int = 1,
                   figsize: tuple[float, float] | None = None):
        try:
            import matplotlib.pyplot as plt
            fig, axes = plt.subplots(
                nrows, ncols,
                figsize=figsize or (6 * ncols, 4 * nrows),
                constrained_layout=True,
            )
            fig.patch.set_facecolor("white")
            return fig, axes
        except ImportError:
            return None, None

    def annotate_bars(self, ax: Any, fmt: str = "{:.1f}", fontsize: int = 8) -> None:
        try:
            for patch in ax.patches:
                h = patch.get_height()
                if h == 0:
                    continue
                ax.annotate(
                    fmt.format(h),
                    xy=(patch.get_x() + patch.get_width() / 2, h),
                    xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=fontsize,
                )
        except Exception:
            pass

    def rotate_xlabels(self, ax: Any, rotation: int = 30) -> None:
        try:
            for label in ax.get_xticklabels():
                label.set_rotation(rotation)
                label.set_ha("right")
        except Exception:
            pass
