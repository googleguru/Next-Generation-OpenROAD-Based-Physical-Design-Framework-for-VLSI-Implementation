from __future__ import annotations
import math
import random
from dataclasses import dataclass

from .bench_parser import Circuit


@dataclass
class PlacementResult:
    circuit_name: str
    hpwl: float                # Half-Perimeter Wire Length (unit = cell widths)
    overflow: float            # fraction of cells with overlap
    num_rows: int
    cells_per_row: int
    die_w: float
    die_h: float
    density: float             # cells / grid_area
    iterations: int
    improved_hpwl: float       # after SA refinement
    hpwl_improvement_pct: float


class ForcedDirectedPlacer:
    """
    Force-directed placement followed by simulated annealing refinement.
    Assigns each cell (x, y) on a continuous grid, then legalises
    to a row-based standard-cell layout.
    """

    CELL_W = 1.0
    CELL_H = 1.0

    def __init__(self, seed: int = 42, sa_iters: int = 8000):
        self.rng = random.Random(seed)
        self.sa_iters = sa_iters

    def place(self, circ: Circuit) -> PlacementResult:
        cells = list(circ.gates.keys())
        n = len(cells)
        if n == 0:
            return PlacementResult(circ.name, 0, 0, 1, 0, 1, 1, 0, 0, 0, 0)

        # Grid dimensions for a roughly square layout
        cols = max(1, math.ceil(math.sqrt(n * 1.3)))
        rows = max(1, math.ceil(n / cols))
        die_w = cols * self.CELL_W
        die_h = rows * self.CELL_H

        # Step 1: Force-directed initial placement
        pos = self._force_directed(circ, cells, die_w, die_h)

        # Step 2: Row legalisation
        pos = self._legalise(pos, cells, cols, rows)

        # Assign to Gate objects
        for name, (x, y) in pos.items():
            if name in circ.gates:
                circ.gates[name].x = x
                circ.gates[name].y = y
                circ.gates[name].col = int(x / self.CELL_W)
                circ.gates[name].row = int(y / self.CELL_H)

        initial_hpwl = self._compute_hpwl(circ, pos)

        # Step 3: SA refinement
        pos, iters = self._sa_refine(circ, cells, pos, cols, rows)

        for name, (x, y) in pos.items():
            if name in circ.gates:
                circ.gates[name].x = x
                circ.gates[name].y = y

        improved_hpwl = self._compute_hpwl(circ, pos)
        improvement = (
            (initial_hpwl - improved_hpwl) / initial_hpwl * 100
            if initial_hpwl > 0 else 0.0
        )

        # Count overflow (cells in same slot)
        slots: set[tuple[int, int]] = set()
        overflow_count = 0
        for x, y in pos.values():
            slot = (int(x), int(y))
            if slot in slots:
                overflow_count += 1
            slots.add(slot)
        overflow_frac = overflow_count / n if n > 0 else 0.0

        return PlacementResult(
            circuit_name=circ.name,
            hpwl=initial_hpwl,
            overflow=overflow_frac,
            num_rows=rows,
            cells_per_row=cols,
            die_w=die_w,
            die_h=die_h,
            density=n / (cols * rows),
            iterations=iters,
            improved_hpwl=improved_hpwl,
            hpwl_improvement_pct=improvement,
        )

    def _force_directed(
        self, circ: Circuit, cells: list[str],
        die_w: float, die_h: float
    ) -> dict[str, tuple[float, float]]:
        # Random initialisation
        pos = {
            c: (self.rng.uniform(0, die_w), self.rng.uniform(0, die_h))
            for c in cells
        }
        # Add PI positions at the left boundary
        pi_positions = {
            pi: (0.0, (i + 1) * die_h / (len(circ.primary_inputs) + 1))
            for i, pi in enumerate(circ.primary_inputs)
        }

        alpha = 0.1  # step size
        for _iter in range(200):
            forces: dict[str, list[float]] = {c: [0.0, 0.0] for c in cells}
            for name, gate in circ.gates.items():
                if name not in pos:
                    continue
                x, y = pos[name]
                for inp in gate.inputs:
                    if inp in pos:
                        xi, yi = pos[inp]
                    elif inp in pi_positions:
                        xi, yi = pi_positions[inp]
                    else:
                        continue
                    dx, dy = xi - x, yi - y
                    forces[name][0] += dx
                    forces[name][1] += dy
                    if inp in forces:
                        forces[inp][0] -= dx
                        forces[inp][1] -= dy
            for c in cells:
                fx, fy = forces[c]
                old_x, old_y = pos[c]
                new_x = max(0, min(die_w, old_x + alpha * fx))
                new_y = max(0, min(die_h, old_y + alpha * fy))
                pos[c] = (new_x, new_y)
            alpha *= 0.99
        return pos

    def _legalise(
        self, pos: dict[str, tuple[float, float]],
        cells: list[str], cols: int, rows: int
    ) -> dict[str, tuple[float, float]]:
        sorted_cells = sorted(cells, key=lambda c: pos[c][1] * 1000 + pos[c][0])
        grid: dict[tuple[int, int], str] = {}
        legal: dict[str, tuple[float, float]] = {}
        for c in sorted_cells:
            x, y = pos[c]
            col = int(min(cols - 1, max(0, round(x / self.CELL_W))))
            row = int(min(rows - 1, max(0, round(y / self.CELL_H))))
            # Find nearest empty slot
            found = False
            for r_off in range(rows):
                for c_off in range(cols):
                    for r_sign in [1, -1]:
                        for c_sign in [1, -1]:
                            nr = row + r_off * r_sign
                            nc = col + c_off * c_sign
                            if 0 <= nr < rows and 0 <= nc < cols:
                                if (nr, nc) not in grid:
                                    grid[(nr, nc)] = c
                                    legal[c] = (nc * self.CELL_W, nr * self.CELL_H)
                                    found = True
                                    break
                        if found:
                            break
                    if found:
                        break
                if found:
                    break
            if not found:
                legal[c] = pos[c]
        return legal

    def _sa_refine(
        self, circ: Circuit, cells: list[str],
        pos: dict[str, tuple[float, float]],
        cols: int, rows: int
    ) -> tuple[dict[str, tuple[float, float]], int]:
        current_pos = dict(pos)
        best_hpwl = self._compute_hpwl(circ, current_pos)
        best_pos = dict(current_pos)
        T = best_hpwl * 0.05
        alpha = 0.97
        iters = 0
        for _ in range(self.sa_iters):
            if len(cells) < 2:
                break
            c1, c2 = self.rng.sample(cells, 2)
            old_p1, old_p2 = current_pos[c1], current_pos[c2]
            current_pos[c1] = old_p2
            current_pos[c2] = old_p1
            new_hpwl = self._compute_hpwl(circ, current_pos)
            delta = new_hpwl - best_hpwl
            if delta < 0 or self.rng.random() < math.exp(-delta / max(T, 1e-9)):
                best_hpwl = new_hpwl
                best_pos = dict(current_pos)
            else:
                current_pos[c1] = old_p1
                current_pos[c2] = old_p2
            T *= alpha
            iters += 1
        return best_pos, iters

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
