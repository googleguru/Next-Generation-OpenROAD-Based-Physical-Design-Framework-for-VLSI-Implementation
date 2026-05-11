from __future__ import annotations
import math
import random
from dataclasses import dataclass, field

from .bench_parser import Circuit, Gate


@dataclass
class FloorplanBlock:
    name: str
    x: float = 0.0
    y: float = 0.0
    w: float = 1.0
    h: float = 1.0
    partition: int = 0
    cell_count: int = 0

    @property
    def area(self) -> float:
        return self.w * self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass
class FloorplanResult:
    circuit_name: str
    blocks: list[FloorplanBlock]
    die_w: float
    die_h: float
    die_area: float
    core_area: float
    utilization: float          # cell area / core area
    num_rows: int
    row_height: float
    wirelength_proxy: float     # HPWL estimate
    aspect_ratio: float


_CELL_W = 1.0   # standard cell width unit
_CELL_H = 1.0   # standard cell height unit
_HALO   = 0.5   # spacing between partitions


class Floorplanner:
    """
    Analytical row-based floorplanner.
    Partitions are placed as rectangular macro blocks;
    simulated annealing minimises inter-block HPWL.
    """

    def __init__(self, seed: int = 42, target_util: float = 0.70):
        self.rng = random.Random(seed)
        self.target_util = target_util

    def plan(self, circ: Circuit, k_partitions: int = 2) -> FloorplanResult:
        # Group cells by partition
        parts: dict[int, list[str]] = {}
        for name, gate in circ.gates.items():
            pid = gate.partition
            parts.setdefault(pid, []).append(name)
        if not parts:
            parts = {0: list(circ.gates.keys())}

        # Estimate block dimensions: sqrt(n) × sqrt(n) aspect ratio
        blocks: list[FloorplanBlock] = []
        total_cells = len(circ.gates) + len(circ.primary_inputs)
        for pid, cells in sorted(parts.items()):
            n = len(cells)
            side = math.sqrt(n * _CELL_W * _CELL_H / self.target_util)
            cols = max(1, round(side / _CELL_W))
            rows_needed = math.ceil(n / cols)
            w = cols * _CELL_W
            h = rows_needed * _CELL_H
            blocks.append(FloorplanBlock(
                name=f"P{pid}", w=w, h=h,
                partition=pid, cell_count=n
            ))

        # SA floorplanning: arrange blocks in a grid to minimise HPWL
        self._sa_place_blocks(blocks, circ)

        # Compute die dimensions (bounding box + margin)
        max_x = max(b.x + b.w for b in blocks) + _HALO * 2
        max_y = max(b.y + b.h for b in blocks) + _HALO * 2
        die_w = max_x
        die_h = max_y
        die_area = die_w * die_h
        cell_area = sum(b.cell_count * _CELL_W * _CELL_H for b in blocks)
        core_area = sum(b.area for b in blocks)
        util = cell_area / die_area if die_area > 0 else 0.0

        # Compute HPWL proxy: sum over all nets of half-perimeter of driver+sinks
        hpwl = self._compute_hpwl(circ, blocks)

        # Compute rows
        row_h = _CELL_H
        num_rows = max(1, round(die_h / row_h))

        # Propagate block coordinates to gates
        for pid, cells in parts.items():
            blk = next((b for b in blocks if b.partition == pid), blocks[0])
            for i, cname in enumerate(cells):
                if cname in circ.gates:
                    col = i % max(1, round(blk.w / _CELL_W))
                    row = i // max(1, round(blk.w / _CELL_W))
                    circ.gates[cname].x = blk.x + col * _CELL_W
                    circ.gates[cname].y = blk.y + row * _CELL_H
                    circ.gates[cname].row = row
                    circ.gates[cname].col = col

        return FloorplanResult(
            circuit_name=circ.name,
            blocks=blocks,
            die_w=die_w,
            die_h=die_h,
            die_area=die_area,
            core_area=core_area,
            utilization=util,
            num_rows=num_rows,
            row_height=row_h,
            wirelength_proxy=hpwl,
            aspect_ratio=die_w / die_h if die_h > 0 else 1.0,
        )

    def _sa_place_blocks(self, blocks: list[FloorplanBlock], circ: Circuit) -> None:
        if len(blocks) == 1:
            blocks[0].x = _HALO
            blocks[0].y = _HALO
            return

        # Initial placement: left-to-right
        x_off = _HALO
        for b in blocks:
            b.x = x_off
            b.y = _HALO
            x_off += b.w + _HALO

        best_cost = self._block_cost(blocks, circ)
        best_placement = [(b.x, b.y) for b in blocks]

        T = 10.0
        alpha = 0.92
        for step in range(2000):
            if len(blocks) < 2:
                break
            # Swap two random blocks
            i, j = self.rng.sample(range(len(blocks)), 2)
            bi, bj = blocks[i], blocks[j]
            old_xi, old_yi = bi.x, bi.y
            old_xj, old_yj = bj.x, bj.y
            bi.x, bi.y = old_xj, old_yj
            bj.x, bj.y = old_xi, old_yi
            cost = self._block_cost(blocks, circ)
            if cost < best_cost or self.rng.random() < math.exp(
                (best_cost - cost) / T
            ):
                best_cost = cost
                best_placement = [(b.x, b.y) for b in blocks]
            else:
                bi.x, bi.y = old_xi, old_yi
                bj.x, bj.y = old_xj, old_yj
            T *= alpha

        for b, (x, y) in zip(blocks, best_placement):
            b.x, b.y = x, y

    def _block_cost(self, blocks: list[FloorplanBlock], circ: Circuit) -> float:
        # Overlap penalty + HPWL
        overlap = 0.0
        for i in range(len(blocks)):
            for j in range(i + 1, len(blocks)):
                bi, bj = blocks[i], blocks[j]
                ox = max(0, min(bi.x + bi.w, bj.x + bj.w) - max(bi.x, bj.x))
                oy = max(0, min(bi.y + bi.h, bj.y + bj.h) - max(bi.y, bj.y))
                overlap += ox * oy
        hpwl = self._compute_hpwl(circ, blocks)
        return overlap * 100.0 + hpwl

    def _compute_hpwl(self, circ: Circuit, blocks: list[FloorplanBlock]) -> float:
        block_map: dict[int, FloorplanBlock] = {b.partition: b for b in blocks}
        hpwl = 0.0
        for name, gate in circ.gates.items():
            if not gate.inputs:
                continue
            pid_driver = gate.partition
            xd = block_map.get(pid_driver, blocks[0]).cx
            yd = block_map.get(pid_driver, blocks[0]).cy
            xs = [block_map.get(circ.gates[inp].partition if inp in circ.gates
                                 else 0, blocks[0]).cx
                  for inp in gate.inputs]
            ys = [block_map.get(circ.gates[inp].partition if inp in circ.gates
                                 else 0, blocks[0]).cy
                  for inp in gate.inputs]
            xs.append(xd)
            ys.append(yd)
            hpwl += (max(xs) - min(xs)) + (max(ys) - min(ys))
        return hpwl
