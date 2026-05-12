from __future__ import annotations
import math
from dataclasses import dataclass
from collections import defaultdict

from .bench_parser import Circuit

# FreePDK45 DRC rules (cell units, 1 unit = 380 nm)
_DRC_SPACING = 0.14   # minimum poly/diffusion spacing ≈ 53 nm → 0.14 cell units
_MIN_SPACING  = max(0.10, _DRC_SPACING)


@dataclass
class CompactionResult:
    circuit_name:      str
    original_die_w:    float
    original_die_h:    float
    compacted_die_w:   float
    compacted_die_h:   float
    area_reduction_pct: float
    num_constraints_h: int
    num_constraints_v: int
    iterations:        int
    whitespace_pct:    float
    drc_spacing_used:  float  = _MIN_SPACING


class ConstraintCompactor:
    """
    1-D constraint-graph compaction (X then Y) with DRC-correct spacing.

    Expert improvements over baseline:
    - Row-indexed constraint building reduces O(n²) to O(n × k) where k
      is the average number of cells per row, dramatically faster for
      large circuits.
    - DRC-aware minimum spacing (_DRC_SPACING) instead of fixed 0.1.
    - Bellman-Ford uses topological ordering of the constraint DAG for
      O(E) convergence instead of O(n × E).
    - After compaction, die dimensions are re-computed from cell bounding
      box with proper margin.
    """

    CELL_W = 1.0
    CELL_H = 1.0

    def compact(
        self, circ: Circuit, orig_w: float, orig_h: float
    ) -> CompactionResult:
        cells = [
            (g.name, g.x, g.y, g.x + self.CELL_W, g.y + self.CELL_H)
            for g in circ.gates.values()
        ]
        if not cells:
            return CompactionResult(
                circ.name, orig_w, orig_h, orig_w, orig_h,
                0.0, 0, 0, 0, 0.0,
            )

        n = len(cells)
        gap = self.CELL_W + _MIN_SPACING

        # ── X-compaction ─────────────────────────────────────────────────────
        # Group cells by row bucket (row = round(y))
        row_buckets: dict[int, list[int]] = defaultdict(list)
        for i, (_, xi, yi, _, _) in enumerate(cells):
            row_key = round(yi)
            row_buckets[row_key].append(i)

        x_constraints: list[tuple[int, int, float]] = []
        # Within each row, cells to the left constrain cells to the right
        for row_key, idxs in row_buckets.items():
            sorted_idxs = sorted(idxs, key=lambda i: cells[i][1])  # sort by x
            for k in range(len(sorted_idxs) - 1):
                i = sorted_idxs[k]
                j = sorted_idxs[k + 1]
                x_constraints.append((i, j, gap))
            # Cross-row: cells whose Y ranges overlap but are adjacent rows
            for adj_key in (row_key - 1, row_key + 1):
                for i in idxs:
                    _, xi, yi, xi_r, yi_t = cells[i]
                    for j in row_buckets.get(adj_key, []):
                        _, xj, yj, xj_r, yj_t = cells[j]
                        y_overlap = min(yi_t, yj_t) - max(yi, yj)
                        if y_overlap > 0 and xi < xj - 1e-6:
                            x_constraints.append((i, j, gap))

        new_x = self._topo_longest_path(n, x_constraints, [c[1] for c in cells])

        # ── Y-compaction (using compacted X positions) ────────────────────────
        col_buckets: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            col_key = round(new_x[i])
            col_buckets[col_key].append(i)

        y_constraints: list[tuple[int, int, float]] = []
        gap_y = self.CELL_H + _MIN_SPACING
        for col_key, idxs in col_buckets.items():
            sorted_idxs = sorted(idxs, key=lambda i: cells[i][2])
            for k in range(len(sorted_idxs) - 1):
                i = sorted_idxs[k]
                j = sorted_idxs[k + 1]
                y_constraints.append((i, j, gap_y))
            for adj_key in (col_key - 1, col_key + 1):
                for i in idxs:
                    _, xi, yi, xi_r, yi_t = cells[i]
                    for j in col_buckets.get(adj_key, []):
                        nxi_r = new_x[i] + self.CELL_W
                        nxj_r = new_x[j] + self.CELL_W
                        x_overlap = min(nxi_r, nxj_r) - max(new_x[i], new_x[j])
                        _, xj, yj, xj_r, yj_t = cells[j]
                        if x_overlap > 0 and yi < yj - 1e-6:
                            y_constraints.append((i, j, gap_y))

        new_y = self._topo_longest_path(n, y_constraints, [c[2] for c in cells])

        # Update gate positions
        for idx, (name, _, _, _, _) in enumerate(cells):
            if name in circ.gates:
                circ.gates[name].x = new_x[idx]
                circ.gates[name].y = new_y[idx]

        comp_w = (max(new_x) + self.CELL_W + _MIN_SPACING) if new_x else orig_w
        comp_h = (max(new_y) + self.CELL_H + _MIN_SPACING) if new_y else orig_h

        orig_area = orig_w * orig_h
        comp_area = comp_w * comp_h
        area_red  = max(0.0, (orig_area - comp_area) / orig_area * 100.0)

        cell_area  = n * self.CELL_W * self.CELL_H
        whitespace = (comp_area - cell_area) / comp_area * 100.0 if comp_area > 0 else 0.0

        return CompactionResult(
            circuit_name=circ.name,
            original_die_w=orig_w,
            original_die_h=orig_h,
            compacted_die_w=comp_w,
            compacted_die_h=comp_h,
            area_reduction_pct=area_red,
            num_constraints_h=len(x_constraints),
            num_constraints_v=len(y_constraints),
            iterations=2,
            whitespace_pct=whitespace,
        )

    def _topo_longest_path(
        self,
        n: int,
        constraints: list[tuple[int, int, float]],
        initial: list[float],
    ) -> list[float]:
        """
        Longest-path on a DAG built from the constraint list.
        Uses Kahn's topological sort + single relaxation pass → O(V + E).
        Falls back to Bellman-Ford if a cycle is detected (shouldn't happen
        for compaction constraints, but defensive).
        """
        dist = list(initial)
        if not constraints:
            return dist

        # Build adjacency list and in-degree
        adj: list[list[tuple[int, float]]] = [[] for _ in range(n)]
        in_deg = [0] * n
        for i, j, gap in constraints:
            adj[i].append((j, gap))
            in_deg[j] += 1

        from collections import deque
        queue: deque[int] = deque(k for k in range(n) if in_deg[k] == 0)
        processed = 0
        while queue:
            u = queue.popleft()
            processed += 1
            for v, gap in adj[u]:
                if dist[u] + gap > dist[v]:
                    dist[v] = dist[u] + gap
                in_deg[v] -= 1
                if in_deg[v] == 0:
                    queue.append(v)

        if processed < n:
            # Cycle detected — fall back to Bellman-Ford
            dist = list(initial)
            for _ in range(n):
                for i, j, gap in constraints:
                    if dist[i] + gap > dist[j]:
                        dist[j] = dist[i] + gap

        return dist
