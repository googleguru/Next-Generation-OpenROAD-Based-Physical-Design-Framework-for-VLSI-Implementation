from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from .bench_parser import Circuit, Gate


@dataclass
class LayoutCell:
    name: str
    gtype: str
    x: float
    y: float
    w: float = 1.0
    h: float = 1.0
    row: int = 0
    col: int = 0
    layer: str = "M1"
    color: str = "#2196F3"
    is_ff: bool = False
    is_pi: bool = False


@dataclass
class LayoutNet:
    driver: str
    sinks: list[str]
    segments: list[tuple[float, float, float, float]]  # x1,y1,x2,y2


@dataclass
class LayoutResult:
    circuit_name: str
    cells: list[LayoutCell]
    nets: list[LayoutNet]
    die_w: float
    die_h: float
    num_rows: int
    num_cells: int
    num_ff: int
    num_pi: int
    routing_layers: list[str]


# Gate type → color mapping (publication-friendly palette)
_GATE_COLOR: dict[str, str] = {
    "AND":  "#1565C0",  # dark blue
    "NAND": "#0288D1",  # light blue
    "OR":   "#2E7D32",  # dark green
    "NOR":  "#66BB6A",  # light green
    "NOT":  "#F57F17",  # amber
    "INV":  "#F57F17",
    "BUFF": "#FBC02D",  # yellow
    "DFF":  "#B71C1C",  # dark red
    "XOR":  "#6A1B9A",  # purple
    "XNOR": "#AB47BC",  # light purple
}


class LayoutEngine:
    """
    Converts placed gate coordinates into a structured LayoutResult
    ready for visualization and GDS II export.
    Generates Manhattan routing segments between cells.
    """

    CELL_W = 1.0
    CELL_H = 1.0

    def generate(self, circ: Circuit) -> LayoutResult:
        cells: list[LayoutCell] = []
        net_dict: dict[str, list[str]] = {}

        # Primary input pseudo-cells (column -1)
        pi_x = -self.CELL_W * 2
        for i, pi in enumerate(circ.primary_inputs):
            cells.append(LayoutCell(
                name=pi, gtype="PI",
                x=pi_x,
                y=i * self.CELL_H,
                w=self.CELL_W * 0.6,
                h=self.CELL_H * 0.6,
                color="#78909C",
                is_pi=True,
            ))
            net_dict[pi] = []

        # Gate cells
        for name, gate in circ.gates.items():
            cells.append(LayoutCell(
                name=name,
                gtype=gate.gtype,
                x=gate.x,
                y=gate.y,
                w=self.CELL_W * 0.85,
                h=self.CELL_H * 0.7,
                row=gate.row,
                col=gate.col,
                color=_GATE_COLOR.get(gate.gtype, "#607D8B"),
                is_ff=gate.is_ff,
            ))
            net_dict.setdefault(name, [])

        # Build nets and routing segments
        cell_pos: dict[str, tuple[float, float]] = {
            c.name: (c.x + c.w / 2, c.y + c.h / 2) for c in cells
        }
        nets: list[LayoutNet] = []
        for name, gate in circ.gates.items():
            if not gate.inputs:
                continue
            sinks = [name]
            segs = []
            dx_pos, dy_pos = cell_pos.get(name, (0.0, 0.0))
            for inp in gate.inputs:
                if inp not in cell_pos:
                    continue
                sx, sy = cell_pos[inp]
                # L-shaped Manhattan route
                segs.append((sx, sy, dx_pos, sy))
                segs.append((dx_pos, sy, dx_pos, dy_pos))
            nets.append(LayoutNet(driver=name, sinks=sinks, segments=segs))

        # Die dimensions
        xs = [c.x for c in cells if not c.is_pi]
        ys = [c.y for c in cells if not c.is_pi]
        die_w = max(xs, default=10) + self.CELL_W * 3
        die_h = max(ys, default=10) + self.CELL_H * 3
        num_rows = max((c.row for c in cells if not c.is_pi), default=1) + 1

        return LayoutResult(
            circuit_name=circ.name,
            cells=cells,
            nets=nets,
            die_w=die_w,
            die_h=die_h,
            num_rows=num_rows,
            num_cells=len(circ.gates),
            num_ff=len(circ.flip_flops),
            num_pi=len(circ.primary_inputs),
            routing_layers=["M1", "M2"],
        )
