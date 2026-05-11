from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

import math

from .bench_parser import Circuit


# Unit gate delays (ps) — technology-independent unit model
_GATE_DELAY: dict[str, float] = {
    "NOT": 40,  "INV": 40,  "BUFF": 50,
    "AND": 60,  "NAND": 55, "OR": 60,  "NOR": 55,
    "XOR": 80,  "XNOR": 80, "DFF": 0,
}
_FF_SETUP  = 50.0  # flip-flop setup time (ps)
_FF_CLK_Q  = 80.0  # clock-to-Q delay (ps)
_WIRE_RC_PS_PER_UNIT = 12.0  # wire RC delay per unit manhattan distance


@dataclass
class TimingNode:
    name: str
    arrival: float   = 0.0   # latest arrival time (ps)
    required: float  = 0.0   # required arrival time (ps)
    slack: float     = 0.0   # required - arrival
    gate_delay: float = 0.0
    wire_delay: float = 0.0

    @property
    def is_critical(self) -> bool:
        return self.slack <= 0.0


@dataclass
class STAResult:
    circuit_name: str
    clock_period_ps: float
    wns_ps: float            # Worst Negative Slack
    tns_ps: float            # Total Negative Slack
    num_violating_paths: int
    critical_path_depth: int
    max_arrival_ps: float
    timing_nodes: dict[str, TimingNode]
    critical_path: list[str]
    num_paths_analyzed: int
    slack_histogram: dict[str, int]  # bucket → count

    @property
    def wns_ns(self) -> float:
        return self.wns_ps / 1000.0

    @property
    def tns_ns(self) -> float:
        return self.tns_ps / 1000.0


class STAEngine:
    """
    Topological-sort based STA with unit-delay + RC wire model.
    Propagates arrival times forward from PIs/FFs and required times backward.
    """

    def __init__(self, clock_period_ps: float = 5000.0):
        self.clock_period_ps = clock_period_ps

    def run(self, circ: Circuit) -> STAResult:
        nodes: dict[str, TimingNode] = {}

        # Initialise PI and FF outputs as sources
        for pi in circ.primary_inputs:
            nodes[pi] = TimingNode(pi, arrival=0.0)
        for ff_name in circ.flip_flops:
            nodes[ff_name] = TimingNode(
                ff_name, arrival=_FF_CLK_Q, gate_delay=_FF_CLK_Q
            )

        # Forward traversal: arrival times
        topo_order = self._topo_sort(circ)
        for name in topo_order:
            gate = circ.gates.get(name)
            if gate is None:
                continue
            if gate.is_ff:
                nodes.setdefault(name, TimingNode(name, arrival=_FF_CLK_Q,
                                                   gate_delay=_FF_CLK_Q))
                continue
            gd = _GATE_DELAY.get(gate.gtype, 60.0)
            max_in_arr = 0.0
            for inp in gate.inputs:
                inp_arr = nodes.get(inp, TimingNode(inp)).arrival
                # Wire delay based on Manhattan distance
                if inp in circ.gates and name in circ.gates:
                    dx = abs(circ.gates[name].x - circ.gates[inp].x)
                    dy = abs(circ.gates[name].y - circ.gates[inp].y)
                    wd = (dx + dy) * _WIRE_RC_PS_PER_UNIT
                else:
                    wd = 0.0
                max_in_arr = max(max_in_arr, inp_arr + wd)
            arrival = max_in_arr + gd
            nodes[name] = TimingNode(
                name, arrival=arrival,
                gate_delay=gd,
                wire_delay=max_in_arr - (max_in_arr - gd) if gd else 0.0,
            )

        # Backward traversal: required arrival times
        # PO required time = clock_period - FF_SETUP
        po_req = self.clock_period_ps - _FF_SETUP
        for po in circ.primary_outputs:
            if po in nodes:
                nodes[po].required = po_req
        for name in reversed(topo_order):
            if name not in nodes:
                continue
            gate = circ.gates.get(name)
            if gate is None:
                continue
            if gate.is_ff:
                nodes[name].required = self.clock_period_ps - _FF_SETUP
                continue
            if nodes[name].required == 0.0:
                nodes[name].required = po_req
            gd = _GATE_DELAY.get(gate.gtype, 60.0)
            req_to_driver = nodes[name].required - gd
            for inp in gate.inputs:
                if inp not in nodes:
                    nodes[inp] = TimingNode(inp, required=req_to_driver)
                else:
                    if nodes[inp].required == 0.0:
                        nodes[inp].required = req_to_driver
                    else:
                        nodes[inp].required = min(nodes[inp].required, req_to_driver)

        # Compute slacks
        for n, tn in nodes.items():
            tn.slack = tn.required - tn.arrival if tn.required else 0.0

        # WNS, TNS
        slacks = [tn.slack for tn in nodes.values()]
        wns = min(slacks) if slacks else 0.0
        neg_slacks = [s for s in slacks if s < 0]
        tns = sum(neg_slacks)
        num_viol = len(neg_slacks)

        # Critical path trace
        critical_path = self._trace_critical_path(circ, nodes, topo_order)

        # Max arrival
        max_arrival = max((tn.arrival for tn in nodes.values()), default=0.0)

        # Histogram
        histogram = self._slack_histogram(nodes)

        return STAResult(
            circuit_name=circ.name,
            clock_period_ps=self.clock_period_ps,
            wns_ps=wns,
            tns_ps=tns,
            num_violating_paths=num_viol,
            critical_path_depth=len(critical_path),
            max_arrival_ps=max_arrival,
            timing_nodes=nodes,
            critical_path=critical_path,
            num_paths_analyzed=len(nodes),
            slack_histogram=histogram,
        )

    def _topo_sort(self, circ: Circuit) -> list[str]:
        visited: set[str] = set()
        order: list[str] = []
        sources = set(circ.primary_inputs) | set(circ.flip_flops)

        def dfs(name: str) -> None:
            if name in visited:
                return
            visited.add(name)
            gate = circ.gates.get(name)
            if gate and not gate.is_ff:
                for inp in gate.inputs:
                    if inp in circ.gates and inp not in sources:
                        dfs(inp)
            order.append(name)

        for name in circ.gates:
            dfs(name)
        return order

    def _trace_critical_path(
        self, circ: Circuit,
        nodes: dict[str, TimingNode],
        order: list[str],
    ) -> list[str]:
        # Find endpoint with worst slack
        po_nodes = [n for n in circ.primary_outputs if n in nodes]
        if not po_nodes:
            return []
        endpoint = min(po_nodes, key=lambda n: nodes[n].slack)

        path = [endpoint]
        current = endpoint
        for _ in range(500):
            gate = circ.gates.get(current)
            if gate is None or gate.is_ff or not gate.inputs:
                break
            worst_inp = max(
                gate.inputs,
                key=lambda i: nodes.get(i, TimingNode(i)).arrival
            )
            if worst_inp not in nodes:
                break
            path.append(worst_inp)
            current = worst_inp
        return list(reversed(path))

    def _slack_histogram(self, nodes: dict[str, TimingNode]) -> dict[str, int]:
        buckets = {
            "< -500ps": 0, "-500~-200ps": 0, "-200~0ps": 0,
            "0~200ps": 0, "200~500ps": 0, "> 500ps": 0
        }
        for tn in nodes.values():
            s = tn.slack
            if s < -500:
                buckets["< -500ps"] += 1
            elif s < -200:
                buckets["-500~-200ps"] += 1
            elif s < 0:
                buckets["-200~0ps"] += 1
            elif s < 200:
                buckets["0~200ps"] += 1
            elif s < 500:
                buckets["200~500ps"] += 1
            else:
                buckets["> 500ps"] += 1
        return buckets
