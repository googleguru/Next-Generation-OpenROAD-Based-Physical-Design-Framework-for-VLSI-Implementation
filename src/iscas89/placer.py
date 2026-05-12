from __future__ import annotations
import math
import random
from dataclasses import dataclass, field

from .bench_parser import Circuit


@dataclass
class PlacementResult:
    circuit_name:       str
    hpwl:               float   # HPWL after force-directed (pre-legalization)
    overflow:           float   # bin-based density overflow fraction (pre-legal)
    num_rows:           int
    cells_per_row:      int
    die_w:              float
    die_h:              float
    density:            float   # mean bin density (0–1)
    iterations:         int
    improved_hpwl:      float   # HPWL after SA + legalization
    hpwl_improvement_pct: float
    max_bin_density:    float = 0.0   # peak bin utilization (0–1)
    row_util_variance:  float = 0.0   # variance of per-row utilization


_TARGET_DENSITY = 0.80   # bin density threshold for overflow check
_BIN_FACTOR     = 4      # die divided into ceil(sqrt(n/k)) × … bins


class ForcedDirectedPlacer:
    """
    Three-phase standard-cell placer:

    1. Force-directed spreading (200 iters with electrostatic repulsion)
       Attractive spring forces along netlist edges + global repulsion
       keep cells from clustering.
    2. Row legalisation — nearest-empty-slot assignment preserving
       relative order.
    3. Pair-swap simulated annealing — minimises HPWL in legal space.

    Expert improvements over baseline:
    - Density spreading via quadratic repulsion term in force model
    - Bin-based overflow metric (OpenROAD OVFL style), computed on
      global (pre-legalisation) positions
    - Timing-driven net weighting (optional STAResult input)
    - SA corrected to track current cost (not just best)
    - Per-row utilisation variance reported
    """

    CELL_W = 1.0
    CELL_H = 1.0

    def __init__(self, seed: int = 42, sa_iters: int = 12_000):
        self.rng = random.Random(seed)
        self.sa_iters = sa_iters

    # ── public ───────────────────────────────────────────────────────────────
    def place(
        self,
        circ: Circuit,
        sta_result=None,   # optional STAResult for timing-driven weighting
    ) -> PlacementResult:
        cells = list(circ.gates.keys())
        n = len(cells)
        if n == 0:
            return PlacementResult(circ.name, 0, 0, 1, 0, 1, 1, 0, 0, 0, 0)

        # Grid: aspect ratio ≈ 1, slight over-provision for whitespace
        cols = max(1, math.ceil(math.sqrt(n * 1.3)))
        rows = max(1, math.ceil(n / cols))
        die_w = cols * self.CELL_W
        die_h = rows * self.CELL_H

        # Build timing-driven net weights
        net_weights = self._build_net_weights(circ, sta_result)

        # Phase 1: force-directed spreading
        pos = self._force_directed(circ, cells, die_w, die_h, net_weights)

        # Bin-based overflow (measure BEFORE legalisation)
        overflow, max_density = self._bin_overflow(pos, die_w, die_h, n)
        pre_legal_hpwl = self._compute_hpwl(circ, pos)

        # Phase 2: legalise to row grid
        pos = self._legalise(pos, cells, cols, rows)

        for name, (x, y) in pos.items():
            if name in circ.gates:
                circ.gates[name].x = x
                circ.gates[name].y = y
                circ.gates[name].col = int(x / self.CELL_W)
                circ.gates[name].row = int(y / self.CELL_H)

        # Phase 3: SA pair-swap refinement
        pos, sa_iters = self._sa_refine(circ, cells, pos, net_weights)

        for name, (x, y) in pos.items():
            if name in circ.gates:
                circ.gates[name].x = x
                circ.gates[name].y = y

        improved_hpwl = self._compute_hpwl(circ, pos)
        improvement = (
            (pre_legal_hpwl - improved_hpwl) / pre_legal_hpwl * 100.0
            if pre_legal_hpwl > 0 else 0.0
        )

        # Per-row utilisation variance
        row_util_var = self._row_utilisation_variance(pos, rows, cols)

        return PlacementResult(
            circuit_name=circ.name,
            hpwl=pre_legal_hpwl,
            overflow=overflow,
            num_rows=rows,
            cells_per_row=cols,
            die_w=die_w,
            die_h=die_h,
            density=n / (cols * rows),
            iterations=sa_iters,
            improved_hpwl=improved_hpwl,
            hpwl_improvement_pct=improvement,
            max_bin_density=max_density,
            row_util_variance=row_util_var,
        )

    # ── Phase 1: force-directed ───────────────────────────────────────────────
    def _force_directed(
        self,
        circ: Circuit,
        cells: list[str],
        die_w: float,
        die_h: float,
        net_weights: dict[str, float],
    ) -> dict[str, tuple[float, float]]:
        # Random seed placement with mild spread
        pos: dict[str, tuple[float, float]] = {}
        for i, c in enumerate(cells):
            # Diagonal spread so cells are not all at origin
            frac = (i + 0.5) / len(cells)
            x0 = self.rng.uniform(frac * die_w * 0.1, die_w * 0.9)
            y0 = self.rng.uniform(frac * die_h * 0.1, die_h * 0.9)
            pos[c] = (x0, y0)

        # PI pseudo-cells on the left boundary
        pi_pos = {
            pi: (0.0, (i + 1) * die_h / (len(circ.primary_inputs) + 1))
            for i, pi in enumerate(circ.primary_inputs)
        }

        alpha = 0.12
        for _iter in range(250):
            forces: dict[str, list[float]] = {c: [0.0, 0.0] for c in cells}

            # Attraction along nets
            for name, gate in circ.gates.items():
                if name not in pos:
                    continue
                x, y = pos[name]
                w = net_weights.get(name, 1.0)
                for inp in gate.inputs:
                    if inp in pos:
                        xi, yi = pos[inp]
                    elif inp in pi_pos:
                        xi, yi = pi_pos[inp]
                    else:
                        continue
                    dx, dy = (xi - x) * w, (yi - y) * w
                    forces[name][0] += dx
                    forces[name][1] += dy
                    if inp in forces:
                        forces[inp][0] -= dx
                        forces[inp][1] -= dy

            # Electrostatic repulsion between close cells (density spreading)
            # Quadratic kernel: repulsion ∝ 1/d² capped at 3 units
            for i, ci in enumerate(cells):
                xi, yi = pos[ci]
                for j in range(i + 1, min(i + 20, len(cells))):  # local window
                    cj = cells[j]
                    xj, yj = pos[cj]
                    dx, dy = xi - xj, yi - yj
                    d2 = dx * dx + dy * dy + 1e-4
                    if d2 < 9.0:  # within 3 units
                        rep = 0.3 / d2
                        forces[ci][0] += rep * dx
                        forces[ci][1] += rep * dy
                        forces[cj][0] -= rep * dx
                        forces[cj][1] -= rep * dy

            for c in cells:
                fx, fy = forces[c]
                ox, oy = pos[c]
                nx = max(0.0, min(die_w - self.CELL_W, ox + alpha * fx))
                ny = max(0.0, min(die_h - self.CELL_H, oy + alpha * fy))
                pos[c] = (nx, ny)

            alpha *= 0.988  # slightly slower cooling for better spread
        return pos

    # ── Bin-based overflow (VLSI-standard metric) ─────────────────────────────
    def _bin_overflow(
        self,
        pos: dict[str, tuple[float, float]],
        die_w: float, die_h: float,
        n: int,
    ) -> tuple[float, float]:
        """Returns (overflow_fraction, max_bin_density)."""
        nbins = max(2, int(math.sqrt(n / _BIN_FACTOR)))
        bw = die_w / nbins
        bh = die_h / nbins
        grid = [[0] * nbins for _ in range(nbins)]

        for x, y in pos.values():
            bx = min(nbins - 1, int(x / bw))
            by = min(nbins - 1, int(y / bh))
            grid[bx][by] += 1

        cap = _TARGET_DENSITY * bw * bh  # cells that fit at target density
        total_bins = nbins * nbins
        ovfl_bins = 0
        max_d = 0.0
        for bx in range(nbins):
            for by in range(nbins):
                d = grid[bx][by] / max(cap, 1.0)
                max_d = max(max_d, d)
                if d > 1.0:
                    ovfl_bins += 1
        return ovfl_bins / total_bins, min(1.0, max_d)

    # ── Phase 2: legalisation ─────────────────────────────────────────────────
    def _legalise(
        self,
        pos: dict[str, tuple[float, float]],
        cells: list[str],
        cols: int, rows: int,
    ) -> dict[str, tuple[float, float]]:
        sorted_cells = sorted(cells, key=lambda c: pos[c][1] * 1e4 + pos[c][0])
        grid: dict[tuple[int, int], str] = {}
        legal: dict[str, tuple[float, float]] = {}
        for c in sorted_cells:
            x, y = pos[c]
            col0 = int(min(cols - 1, max(0, round(x / self.CELL_W))))
            row0 = int(min(rows - 1, max(0, round(y / self.CELL_H))))
            placed = False
            for r_off in range(rows):
                for c_off in range(cols):
                    for rsign in (1, -1):
                        for csign in (1, -1):
                            nr = row0 + r_off * rsign
                            nc = col0 + c_off * csign
                            if 0 <= nr < rows and 0 <= nc < cols:
                                if (nr, nc) not in grid:
                                    grid[(nr, nc)] = c
                                    legal[c] = (nc * self.CELL_W, nr * self.CELL_H)
                                    placed = True
                                    break
                        if placed:
                            break
                    if placed:
                        break
                if placed:
                    break
            if not placed:
                legal[c] = pos[c]
        return legal

    # ── Phase 3: SA pair-swap ─────────────────────────────────────────────────
    def _sa_refine(
        self,
        circ: Circuit,
        cells: list[str],
        pos: dict[str, tuple[float, float]],
        net_weights: dict[str, float],
    ) -> tuple[dict[str, tuple[float, float]], int]:
        current_pos = dict(pos)
        current_hpwl = self._compute_hpwl_weighted(circ, current_pos, net_weights)
        best_hpwl = current_hpwl
        best_pos   = dict(current_pos)

        T = max(current_hpwl * 0.05, 1.0)
        alpha = 0.995
        iters = 0

        for _ in range(self.sa_iters):
            if len(cells) < 2:
                break
            c1, c2 = self.rng.sample(cells, 2)
            p1, p2 = current_pos[c1], current_pos[c2]
            current_pos[c1], current_pos[c2] = p2, p1

            new_hpwl = self._compute_hpwl_weighted(circ, current_pos, net_weights)
            delta = new_hpwl - current_hpwl

            if delta < 0 or self.rng.random() < math.exp(-delta / max(T, 1e-9)):
                current_hpwl = new_hpwl   # accept: update current cost
                if new_hpwl < best_hpwl:
                    best_hpwl = new_hpwl
                    best_pos  = dict(current_pos)
            else:
                current_pos[c1], current_pos[c2] = p1, p2  # revert

            T *= alpha
            iters += 1

        return best_pos, iters

    # ── utilities ─────────────────────────────────────────────────────────────
    def _compute_hpwl(
        self, circ: Circuit, pos: dict[str, tuple[float, float]]
    ) -> float:
        hpwl = 0.0
        for name, gate in circ.gates.items():
            if not gate.inputs or name not in pos:
                continue
            xs = [pos[name][0]]
            ys = [pos[name][1]]
            for inp in gate.inputs:
                if inp in pos:
                    xs.append(pos[inp][0])
                    ys.append(pos[inp][1])
            hpwl += (max(xs) - min(xs)) + (max(ys) - min(ys))
        return hpwl

    def _compute_hpwl_weighted(
        self,
        circ: Circuit,
        pos: dict[str, tuple[float, float]],
        weights: dict[str, float],
    ) -> float:
        hpwl = 0.0
        for name, gate in circ.gates.items():
            if not gate.inputs or name not in pos:
                continue
            w = weights.get(name, 1.0)
            xs = [pos[name][0]]
            ys = [pos[name][1]]
            for inp in gate.inputs:
                if inp in pos:
                    xs.append(pos[inp][0])
                    ys.append(pos[inp][1])
            hpwl += w * ((max(xs) - min(xs)) + (max(ys) - min(ys)))
        return hpwl

    def _build_net_weights(
        self, circ: Circuit, sta_result
    ) -> dict[str, float]:
        """
        Assign higher force weights to nets on or near the critical path.
        Weight = 1 + criticality × 3, where criticality = max(0, -slack) / abs(wns).
        """
        weights: dict[str, float] = {n: 1.0 for n in circ.gates}
        if sta_result is None:
            return weights
        try:
            wns = sta_result.wns_ps
            if wns >= 0:
                return weights
            for name, node in sta_result.timing_nodes.items():
                if name in weights and node.slack < float("inf"):
                    crit = max(0.0, -node.slack / abs(wns))
                    weights[name] = 1.0 + crit * 3.0
        except Exception:
            pass
        return weights

    def _row_utilisation_variance(
        self,
        pos: dict[str, tuple[float, float]],
        rows: int, cols: int,
    ) -> float:
        """Variance of cells-per-row normalised by mean."""
        row_counts = [0] * rows
        for x, y in pos.values():
            r = min(rows - 1, int(round(y / self.CELL_H)))
            if 0 <= r < rows:
                row_counts[r] += 1
        mean = sum(row_counts) / max(1, rows)
        if mean == 0:
            return 0.0
        return sum((c - mean) ** 2 for c in row_counts) / rows / (mean * mean)
