from __future__ import annotations
import math
import random
from dataclasses import dataclass, field

from .bench_parser import Circuit, Gate


@dataclass
class FloorplanBlock:
    name:       str
    x:          float = 0.0
    y:          float = 0.0
    w:          float = 1.0
    h:          float = 1.0
    partition:  int   = 0
    cell_count: int   = 0

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
    circuit_name:     str
    blocks:           list[FloorplanBlock]
    die_w:            float
    die_h:            float
    die_area:         float
    core_area:        float
    utilization:      float   # cell area / die area (with margins)
    core_utilization: float   # cell area / core_area (without halos)
    num_rows:         int
    row_height:       float
    wirelength_proxy: float   # HPWL estimate
    aspect_ratio:     float


_CELL_W   = 1.0    # standard cell width  (cell units)
_CELL_H   = 1.0    # standard cell height (cell units)
_IO_MARGIN = 1.0   # I/O ring margin around core (cell units)
_MIN_GAP   = 0.2   # minimum gap between partition blocks


class Floorplanner:
    """
    Row-based analytical floorplanner with SA block placement.

    Expert improvements:
    - Correct utilisation: cell_area / core_area (not die area) for
      core utilisation; die utilisation accounts for I/O margins.
    - SA explores both horizontal and vertical block arrangements,
      and also random x/y perturbations (not only swaps).
    - After SA, blocks are compacted left-bottom with minimum spacing.
    - Die dimensions respect a configurable target aspect ratio.
    - Gate coordinates propagated to integer row/col slots within blocks.
    """

    def __init__(
        self,
        seed: int = 42,
        target_util: float = 0.70,
        target_aspect: float = 1.0,   # die W/H target; 1 = square
    ):
        self.rng = random.Random(seed)
        self.target_util = target_util
        self.target_aspect = target_aspect

    # ── public ───────────────────────────────────────────────────────────────
    def plan(self, circ: Circuit, k_partitions: int = 2) -> FloorplanResult:
        # Group cells by partition id
        parts: dict[int, list[str]] = {}
        for name, gate in circ.gates.items():
            parts.setdefault(gate.partition, []).append(name)
        if not parts:
            parts = {0: list(circ.gates.keys())}

        # Build FloorplanBlock with dimensions sized for target utilisation
        blocks: list[FloorplanBlock] = []
        for pid, cells in sorted(parts.items()):
            n = len(cells)
            # Core area needed = cell_area / target_util
            core_needed = (n * _CELL_W * _CELL_H) / self.target_util
            # Aspect ratio for this block ≈ target_aspect
            blk_h = math.sqrt(core_needed / self.target_aspect)
            blk_w = core_needed / blk_h
            # Snap to integer rows/cols
            cols = max(1, round(blk_w / _CELL_W))
            rows = max(1, math.ceil(n / cols))
            blocks.append(FloorplanBlock(
                name=f"P{pid}",
                w=cols * _CELL_W,
                h=rows * _CELL_H,
                partition=pid,
                cell_count=n,
            ))

        # SA placement of blocks with multi-move types
        self._sa_place_blocks(blocks, circ)

        # Compact: shift blocks to fill gaps (greedy left-bottom packing)
        self._compact_blocks(blocks)

        # Die = core + I/O margins on all sides
        max_x = max(b.x + b.w for b in blocks) + _IO_MARGIN
        max_y = max(b.y + b.h for b in blocks) + _IO_MARGIN
        # Enforce target aspect ratio on die
        if max_x / max(max_y, 1e-9) < self.target_aspect * 0.8:
            max_x = max_y * self.target_aspect
        elif max_x / max(max_y, 1e-9) > self.target_aspect * 1.2:
            max_y = max_x / self.target_aspect

        die_w = max_x + _IO_MARGIN
        die_h = max_y + _IO_MARGIN
        die_area  = die_w * die_h
        core_area = sum(b.area for b in blocks)
        cell_area = sum(b.cell_count * _CELL_W * _CELL_H for b in blocks)

        die_util  = cell_area / die_area  if die_area  > 0 else 0.0
        core_util = cell_area / core_area if core_area > 0 else 0.0

        hpwl    = self._compute_hpwl(circ, blocks)
        row_h   = _CELL_H
        num_rows = max(1, round(die_h / row_h))

        # Propagate block coordinates to gate objects
        for pid, cells in parts.items():
            blk = next((b for b in blocks if b.partition == pid), blocks[0])
            cols_in_blk = max(1, round(blk.w / _CELL_W))
            for i, cname in enumerate(cells):
                if cname in circ.gates:
                    col = i % cols_in_blk
                    row = i // cols_in_blk
                    circ.gates[cname].x   = blk.x + col * _CELL_W
                    circ.gates[cname].y   = blk.y + row * _CELL_H
                    circ.gates[cname].row = row
                    circ.gates[cname].col = col

        return FloorplanResult(
            circuit_name=circ.name,
            blocks=blocks,
            die_w=die_w,
            die_h=die_h,
            die_area=die_area,
            core_area=core_area,
            utilization=die_util,
            core_utilization=core_util,
            num_rows=num_rows,
            row_height=row_h,
            wirelength_proxy=hpwl,
            aspect_ratio=die_w / die_h if die_h > 0 else 1.0,
        )

    # ── SA block placement ────────────────────────────────────────────────────
    def _sa_place_blocks(
        self, blocks: list[FloorplanBlock], circ: Circuit
    ) -> None:
        if len(blocks) == 1:
            blocks[0].x = _IO_MARGIN
            blocks[0].y = _IO_MARGIN
            return

        # Initial placement: try both horizontal and vertical arrangement,
        # pick the one with lower AR deviation
        self._init_horizontal(blocks)
        cost_h = self._block_cost(blocks, circ)
        placement_h = [(b.x, b.y, b.w, b.h) for b in blocks]

        self._init_vertical(blocks)
        cost_v = self._block_cost(blocks, circ)

        if cost_h < cost_v:
            for b, (x, y, w, h) in zip(blocks, placement_h):
                b.x, b.y = x, y

        best_cost = self._block_cost(blocks, circ)
        best_pl   = [(b.x, b.y) for b in blocks]

        T = max(10.0, best_cost * 0.1)
        alpha = 0.94
        for _step in range(3000):
            if len(blocks) < 2:
                break
            move = self.rng.random()
            if move < 0.5:
                # Swap two block positions
                i, j = self.rng.sample(range(len(blocks)), 2)
                bi, bj = blocks[i], blocks[j]
                bi.x, bj.x = bj.x, bi.x
                bi.y, bj.y = bj.y, bi.y
            elif move < 0.75:
                # Translate one block by a small random offset
                i = self.rng.randrange(len(blocks))
                dx = self.rng.uniform(-blocks[i].w, blocks[i].w)
                dy = self.rng.uniform(-blocks[i].h, blocks[i].h)
                blocks[i].x = max(0.0, blocks[i].x + dx)
                blocks[i].y = max(0.0, blocks[i].y + dy)
                old_pos = None
            else:
                # Rotate a block (swap w↔h)
                i = self.rng.randrange(len(blocks))
                blocks[i].w, blocks[i].h = blocks[i].h, blocks[i].w
                old_pos = None

            cost = self._block_cost(blocks, circ)
            if cost < best_cost or self.rng.random() < math.exp(
                (best_cost - cost) / max(T, 1e-9)
            ):
                best_cost = cost
                best_pl   = [(b.x, b.y) for b in blocks]
            else:
                # Revert
                if move < 0.5:
                    blocks[i].x, blocks[j].x = blocks[j].x, blocks[i].x
                    blocks[i].y, blocks[j].y = blocks[j].y, blocks[i].y
                elif move < 0.75:
                    blocks[i].x -= dx
                    blocks[i].y -= dy
                else:
                    blocks[i].w, blocks[i].h = blocks[i].h, blocks[i].w
            T *= alpha

        for b, (x, y) in zip(blocks, best_pl):
            b.x, b.y = x, y

    def _init_horizontal(self, blocks: list[FloorplanBlock]) -> None:
        x = _IO_MARGIN
        for b in blocks:
            b.x = x; b.y = _IO_MARGIN
            x += b.w + _MIN_GAP

    def _init_vertical(self, blocks: list[FloorplanBlock]) -> None:
        y = _IO_MARGIN
        for b in blocks:
            b.x = _IO_MARGIN; b.y = y
            y += b.h + _MIN_GAP

    # ── Greedy left-bottom compaction ─────────────────────────────────────────
    def _compact_blocks(self, blocks: list[FloorplanBlock]) -> None:
        """Push each block left then down as far as possible."""
        for b in sorted(blocks, key=lambda blk: (blk.x, blk.y)):
            # Push left
            min_x = _IO_MARGIN
            for other in blocks:
                if other is b:
                    continue
                y_overlap = (
                    min(b.y + b.h, other.y + other.h) - max(b.y, other.y)
                )
                if y_overlap > 0 and other.x + other.w <= b.x:
                    min_x = max(min_x, other.x + other.w + _MIN_GAP)
            b.x = min_x
            # Push down
            min_y = _IO_MARGIN
            for other in blocks:
                if other is b:
                    continue
                x_overlap = (
                    min(b.x + b.w, other.x + other.w) - max(b.x, other.x)
                )
                if x_overlap > 0 and other.y + other.h <= b.y:
                    min_y = max(min_y, other.y + other.h + _MIN_GAP)
            b.y = min_y

    # ── cost function ─────────────────────────────────────────────────────────
    def _block_cost(
        self, blocks: list[FloorplanBlock], circ: Circuit
    ) -> float:
        # Overlap penalty (weighted heavily)
        overlap = 0.0
        for i in range(len(blocks)):
            for j in range(i + 1, len(blocks)):
                bi, bj = blocks[i], blocks[j]
                ox = max(0.0, min(bi.x + bi.w, bj.x + bj.w) - max(bi.x, bj.x))
                oy = max(0.0, min(bi.y + bi.h, bj.y + bj.h) - max(bi.y, bj.y))
                overlap += ox * oy

        # Aspect ratio penalty
        max_x = max(b.x + b.w for b in blocks)
        max_y = max(b.y + b.h for b in blocks)
        ar = max_x / max(max_y, 1e-9)
        ar_penalty = abs(ar - self.target_aspect) * max_x * max_y * 0.1

        hpwl = self._compute_hpwl(circ, blocks)
        return overlap * 200.0 + ar_penalty + hpwl

    def _compute_hpwl(
        self, circ: Circuit, blocks: list[FloorplanBlock]
    ) -> float:
        bmap: dict[int, FloorplanBlock] = {b.partition: b for b in blocks}
        default = blocks[0]
        hpwl = 0.0
        for name, gate in circ.gates.items():
            if not gate.inputs:
                continue
            xd = bmap.get(gate.partition, default).cx
            yd = bmap.get(gate.partition, default).cy
            xs = [
                bmap.get(
                    circ.gates[inp].partition if inp in circ.gates else 0,
                    default,
                ).cx
                for inp in gate.inputs
            ]
            ys = [
                bmap.get(
                    circ.gates[inp].partition if inp in circ.gates else 0,
                    default,
                ).cy
                for inp in gate.inputs
            ]
            xs.append(xd); ys.append(yd)
            hpwl += (max(xs) - min(xs)) + (max(ys) - min(ys))
        return hpwl
