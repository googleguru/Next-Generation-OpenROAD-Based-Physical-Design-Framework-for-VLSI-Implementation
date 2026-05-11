from __future__ import annotations
import math
from dataclasses import dataclass, field

from .bench_parser import Circuit


@dataclass
class CompactionResult:
    circuit_name: str
    original_die_w: float
    original_die_h: float
    compacted_die_w: float
    compacted_die_h: float
    area_reduction_pct: float
    num_constraints_h: int
    num_constraints_v: int
    iterations: int
    whitespace_pct: float


class ConstraintCompactor:
    """
    1-D constraint-graph compaction (X then Y).
    Builds horizontal and vertical constraint graphs from placed cell positions,
    finds longest paths (critical paths), and computes minimum die dimensions.
    """

    CELL_W = 1.0
    CELL_H = 1.0
    MIN_SPACING = 0.1

    def compact(self, circ: Circuit, orig_w: float, orig_h: float) -> CompactionResult:
        cells = [
            (g.name, g.x, g.y, g.x + self.CELL_W, g.y + self.CELL_H)
            for g in circ.gates.values()
        ]
        if not cells:
            return CompactionResult(circ.name, orig_w, orig_h,
                                     orig_w, orig_h, 0.0, 0, 0, 0, 0.0)

        # X-compaction
        x_constraints: list[tuple[int, int, float]] = []  # (i, j, min_gap)
        for i in range(len(cells)):
            for j in range(len(cells)):
                if i == j:
                    continue
                _, xi, yi, xi_r, yi_t = cells[i]
                _, xj, yj, xj_r, yj_t = cells[j]
                # j must be to the right of i if their y-ranges overlap
                y_overlap = min(yi_t, yj_t) - max(yi, yj)
                if y_overlap > 0 and xi < xj:
                    x_constraints.append((i, j, self.CELL_W + self.MIN_SPACING))

        new_x = self._longest_path_1d(len(cells), x_constraints,
                                        [c[1] for c in cells])

        # Y-compaction
        y_constraints: list[tuple[int, int, float]] = []
        for i in range(len(cells)):
            for j in range(len(cells)):
                if i == j:
                    continue
                _, xi, yi, xi_r, _ = cells[i]
                _, xj, yj, xj_r, _ = cells[j]
                x_overlap_new = min(new_x[i] + self.CELL_W, new_x[j] + self.CELL_W) \
                                - max(new_x[i], new_x[j])
                if x_overlap_new > 0 and yi < yj:
                    y_constraints.append((i, j, self.CELL_H + self.MIN_SPACING))

        orig_ys = [c[2] for c in cells]
        new_y = self._longest_path_1d(len(cells), y_constraints, orig_ys)

        # Update gate positions
        for idx, (name, _, _, _, _) in enumerate(cells):
            if name in circ.gates:
                circ.gates[name].x = new_x[idx]
                circ.gates[name].y = new_y[idx]

        comp_w = max(new_x) + self.CELL_W + self.MIN_SPACING if new_x else orig_w
        comp_h = max(new_y) + self.CELL_H + self.MIN_SPACING if new_y else orig_h

        orig_area = orig_w * orig_h
        comp_area = comp_w * comp_h
        area_red = (orig_area - comp_area) / orig_area * 100 if orig_area > 0 else 0.0

        cell_area = len(cells) * self.CELL_W * self.CELL_H
        whitespace = (comp_area - cell_area) / comp_area * 100 if comp_area > 0 else 0.0

        return CompactionResult(
            circuit_name=circ.name,
            original_die_w=orig_w,
            original_die_h=orig_h,
            compacted_die_w=comp_w,
            compacted_die_h=comp_h,
            area_reduction_pct=max(0.0, area_red),
            num_constraints_h=len(x_constraints),
            num_constraints_v=len(y_constraints),
            iterations=2,
            whitespace_pct=whitespace,
        )

    def _longest_path_1d(
        self,
        n: int,
        constraints: list[tuple[int, int, float]],
        original: list[float],
    ) -> list[float]:
        dist = [original[i] if i < len(original) else 0.0 for i in range(n)]
        # Bellman-Ford style relaxation
        for _ in range(n):
            for i, j, gap in constraints:
                if dist[i] + gap > dist[j]:
                    dist[j] = dist[i] + gap
        return dist
