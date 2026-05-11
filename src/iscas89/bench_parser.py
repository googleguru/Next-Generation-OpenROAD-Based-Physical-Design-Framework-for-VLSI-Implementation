from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Gate:
    name: str
    gtype: str          # AND OR NOT NAND NOR BUFF DFF XOR XNOR INV
    inputs: list[str]   # list of driving net / gate names
    # Physical coordinates (set by placer)
    x: float = 0.0
    y: float = 0.0
    width: float = 1.0
    height: float = 1.0
    row: int = 0
    col: int = 0
    partition: int = 0

    @property
    def is_ff(self) -> bool:
        return self.gtype.upper() == "DFF"

    @property
    def drive_strength(self) -> int:
        if self.gtype in ("NOT", "INV", "BUFF"):
            return 1
        return len(self.inputs)


@dataclass
class Circuit:
    name: str
    primary_inputs: list[str] = field(default_factory=list)
    primary_outputs: list[str] = field(default_factory=list)
    gates: dict[str, Gate] = field(default_factory=dict)

    # Derived after parse
    levels: dict[str, int] = field(default_factory=dict)   # gate → topo level
    fanout: dict[str, list[str]] = field(default_factory=dict)  # gate → list of sinks

    @property
    def flip_flops(self) -> list[str]:
        return [n for n, g in self.gates.items() if g.is_ff]

    @property
    def combinational_gates(self) -> list[str]:
        return [n for n, g in self.gates.items() if not g.is_ff]

    @property
    def num_cells(self) -> int:
        return len(self.gates)

    @property
    def num_nets(self) -> int:
        return len(self.gates) + len(self.primary_inputs)

    def stats(self) -> dict:
        gate_counts: dict[str, int] = {}
        for g in self.gates.values():
            gate_counts[g.gtype] = gate_counts.get(g.gtype, 0) + 1
        return {
            "name": self.name,
            "primary_inputs": len(self.primary_inputs),
            "primary_outputs": len(self.primary_outputs),
            "flip_flops": len(self.flip_flops),
            "combinational_gates": len(self.combinational_gates),
            "total_cells": self.num_cells,
            "max_level": max(self.levels.values()) if self.levels else 0,
            "gate_types": gate_counts,
            "max_fanout": max(
                (len(v) for v in self.fanout.values()), default=0
            ),
            "avg_fanout": (
                sum(len(v) for v in self.fanout.values()) / len(self.fanout)
                if self.fanout else 0.0
            ),
        }


_GATE_RE = re.compile(
    r'^\s*(\w+)\s*=\s*(\w+)\s*\(([^)]*)\)',
    re.IGNORECASE,
)
_INPUT_RE  = re.compile(r'^\s*INPUT\s*\(\s*(\w+)\s*\)',  re.IGNORECASE)
_OUTPUT_RE = re.compile(r'^\s*OUTPUT\s*\(\s*(\w+)\s*\)', re.IGNORECASE)


class BenchParser:
    def parse(self, path: Path) -> Circuit:
        path = Path(path)
        circ = Circuit(name=path.stem)
        for line in path.read_text().splitlines():
            line = line.split("#")[0].strip()
            if not line:
                continue
            m = _INPUT_RE.match(line)
            if m:
                circ.primary_inputs.append(m.group(1))
                continue
            m = _OUTPUT_RE.match(line)
            if m:
                circ.primary_outputs.append(m.group(1))
                continue
            m = _GATE_RE.match(line)
            if m:
                out_name, gtype, args = m.group(1), m.group(2).upper(), m.group(3)
                inputs = [a.strip() for a in args.split(",") if a.strip()]
                circ.gates[out_name] = Gate(
                    name=out_name, gtype=gtype, inputs=inputs
                )
        self._compute_levels(circ)
        self._compute_fanout(circ)
        return circ

    def _compute_levels(self, circ: Circuit) -> None:
        level: dict[str, int] = {}
        for pi in circ.primary_inputs:
            level[pi] = 0
        # FFs output is treated as level 0 (break sequential loops)
        for ff in circ.flip_flops:
            level[ff] = 0

        changed = True
        iterations = 0
        while changed and iterations < 200:
            changed = False
            iterations += 1
            for name, gate in circ.gates.items():
                if name in level:
                    continue
                if gate.is_ff:
                    level[name] = 0
                    changed = True
                    continue
                input_levels = [level.get(inp) for inp in gate.inputs]
                if all(v is not None for v in input_levels):
                    new_level = max(input_levels) + 1  # type: ignore
                    level[name] = new_level
                    changed = True
        # Assign any remaining unresolved as level 1
        for name in circ.gates:
            if name not in level:
                level[name] = 1
        circ.levels = level

    def _compute_fanout(self, circ: Circuit) -> None:
        fanout: dict[str, list[str]] = {}
        for pi in circ.primary_inputs:
            fanout[pi] = []
        for name in circ.gates:
            fanout[name] = []
        for name, gate in circ.gates.items():
            for inp in gate.inputs:
                fanout.setdefault(inp, []).append(name)
        circ.fanout = fanout
