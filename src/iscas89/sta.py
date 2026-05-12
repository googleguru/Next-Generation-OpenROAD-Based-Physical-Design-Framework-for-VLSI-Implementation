from __future__ import annotations
from dataclasses import dataclass, field
import math

from .bench_parser import Circuit

# ── FreePDK45-calibrated unit gate delays (ps) ───────────────────────────────
# Values based on 45 nm NAND-equivalent timing models at nominal PVT
_GATE_DELAY: dict[str, float] = {
    "NOT": 26,  "INV": 26,  "BUFF": 38,
    "AND": 52,  "NAND": 38, "OR": 52,  "NOR": 38,
    "XOR": 74,  "XNOR": 74,
    "DFF": 0,   # DFF: clk-to-Q handled separately
}
_FF_CLK_Q       = 60.0   # ps — clock-to-Q propagation (FreePDK45)
_FF_SETUP       = 18.0   # ps — setup time
_FF_HOLD        = 5.0    # ps — hold time (informational)
_CLK_UNCERTAINTY = 50.0  # ps — total clock uncertainty (jitter + skew)

# Wire RC: Elmore model per unit Manhattan distance
# Using M2 (regional routing layer) parameters at 45 nm
# R = 0.3 Ω/sq × (1/0.070 μm) = 4.3 Ω/μm × 0.38 μm/unit = 1.63 Ω/unit
# C = 0.20 fF/μm × 0.38 μm/unit = 0.076 fF/unit
# Wire RC delay (lumped) ≈ 0.7 × R_wire × C_wire per unit²  (Elmore)
# For typical fan-out driving resistance 1kΩ:  τ ≈ R_drv × C_wire ≈ dominant
_WIRE_RC_PS_PER_UNIT = 8.0   # ps per unit Manhattan distance (M2, 45 nm)


@dataclass
class TimingNode:
    name: str
    arrival:     float = 0.0        # latest arrival time (ps)
    required:    float = float("inf")  # required arrival time (ps); inf = unconstrained
    gate_delay:  float = 0.0
    wire_delay:  float = 0.0        # total wire delay from slowest input

    @property
    def slack(self) -> float:
        # Unconstrained nodes (no timing endpoint downstream) are given a
        # large positive slack so they don't pollute histogram or WNS.
        if self.required == float("inf"):
            return 9999.0
        return self.required - self.arrival

    @property
    def is_critical(self) -> bool:
        return self.slack <= 0.0


@dataclass
class STAResult:
    circuit_name:       str
    clock_period_ps:    float
    clock_uncertainty_ps: float
    wns_ps:             float   # Worst Negative Slack
    tns_ps:             float   # Total Negative Slack (sum of all negative slacks)
    num_violating_paths: int
    critical_path_depth: int
    max_arrival_ps:     float
    timing_nodes:       dict[str, TimingNode]
    critical_path:      list[str]
    num_paths_analyzed: int
    slack_histogram:    dict[str, int]
    # Path type counts
    path_pi_to_po:      int = 0
    path_ff_to_ff:      int = 0
    path_ff_to_po:      int = 0
    path_pi_to_ff:      int = 0

    @property
    def wns_ns(self) -> float:
        return self.wns_ps / 1000.0

    @property
    def tns_ns(self) -> float:
        return self.tns_ps / 1000.0

    @property
    def timing_margin_ps(self) -> float:
        """Remaining slack after uncertainty deduction."""
        return self.wns_ps


class STAEngine:
    """
    Topological-sort based STA (cycle-based, setup-time check).

    Forward pass: propagates latest arrival times from PI/FF-Q sources.
    Backward pass: propagates earliest required times from PO/FF-D sinks.
    Slack = required − arrival.  Negative slack → setup violation.

    Improvements over baseline:
    - Clock uncertainty (jitter + skew) subtracted from required window
    - Correct FF backward propagation (D-pin required ≠ Q-pin required)
    - Per-arc wire delay tracked in TimingNode
    - Timing path type identification (PI→PO, FF→FF, FF→PO, PI→FF)
    - Required-time sentinel is float('inf') — no false-0 confusion
    """

    def __init__(
        self,
        clock_period_ps: float = 5000.0,
        clock_uncertainty_ps: float = _CLK_UNCERTAINTY,
    ):
        self.clock_period_ps = clock_period_ps
        self.clock_uncertainty_ps = clock_uncertainty_ps

    # ── public API ──────────────────────────────────────────────────────────
    def run(self, circ: Circuit) -> STAResult:
        nodes: dict[str, TimingNode] = {}

        # Seed sources: PI arrival = 0, FF Q-output arrival = clk-to-Q
        for pi in circ.primary_inputs:
            nodes[pi] = TimingNode(pi, arrival=0.0, required=float("inf"))
        for ff_name in circ.flip_flops:
            nodes[ff_name] = TimingNode(
                ff_name, arrival=_FF_CLK_Q, gate_delay=_FF_CLK_Q,
                required=float("inf"),
            )

        topo_order = self._topo_sort(circ)

        # ── Forward: arrival times ──────────────────────────────────────────
        for name in topo_order:
            gate = circ.gates.get(name)
            if gate is None or gate.is_ff:
                continue
            gd = _GATE_DELAY.get(gate.gtype, 52.0)
            max_in_arr = 0.0
            worst_wd   = 0.0
            for inp in gate.inputs:
                inp_node = nodes.get(inp)
                inp_arr  = inp_node.arrival if inp_node else 0.0
                # Wire RC delay proportional to Manhattan distance
                wd = self._wire_delay(circ, inp, name)
                total = inp_arr + wd
                if total > max_in_arr:
                    max_in_arr = total
                    worst_wd   = wd
            arrival = max_in_arr + gd
            nodes[name] = TimingNode(
                name, arrival=arrival,
                gate_delay=gd, wire_delay=worst_wd,
            )

        # ── Backward: required times ────────────────────────────────────────
        # Effective timing window = clock_period - setup - uncertainty
        window = self.clock_period_ps - _FF_SETUP - self.clock_uncertainty_ps

        # PO endpoints constrained to output delay = window
        for po in circ.primary_outputs:
            n = nodes.setdefault(po, TimingNode(po))
            n.required = min(n.required, window)

        for name in reversed(topo_order):
            gate = circ.gates.get(name)
            if gate is None:
                continue

            if gate.is_ff:
                # D-pin timing endpoint: set required on all D inputs
                for inp in gate.inputs:
                    n = nodes.setdefault(inp, TimingNode(inp))
                    n.required = min(n.required, window)
                # No backward propagation through FF (sequential boundary)
                continue

            n = nodes.get(name)
            if n is None or n.required == float("inf"):
                continue

            gd = _GATE_DELAY.get(gate.gtype, 52.0)
            for inp in gate.inputs:
                wd = self._wire_delay(circ, inp, name)
                req_at_inp = n.required - gd - wd
                inp_n = nodes.setdefault(inp, TimingNode(inp))
                inp_n.required = min(inp_n.required, req_at_inp)

        # ── Finalise slacks ─────────────────────────────────────────────────
        constrained = {
            nm: nd for nm, nd in nodes.items()
            if nd.required < float("inf")
        }
        slacks = [nd.slack for nd in constrained.values()]
        wns = min(slacks) if slacks else 0.0
        tns = sum(s for s in slacks if s < 0.0)
        num_viol = sum(1 for s in slacks if s < 0.0)

        critical_path = self._trace_critical_path(circ, nodes, topo_order)
        max_arrival   = max(
            (nd.arrival for nd in nodes.values()), default=0.0
        )
        histogram = self._slack_histogram(constrained)

        # ── Path type statistics ─────────────────────────────────────────────
        pi_set = set(circ.primary_inputs)
        ff_set = set(circ.flip_flops)
        po_set = set(circ.primary_outputs)
        pc = self._count_path_types(circ, nodes, pi_set, ff_set, po_set)

        return STAResult(
            circuit_name=circ.name,
            clock_period_ps=self.clock_period_ps,
            clock_uncertainty_ps=self.clock_uncertainty_ps,
            wns_ps=wns,
            tns_ps=tns,
            num_violating_paths=num_viol,
            critical_path_depth=len(critical_path),
            max_arrival_ps=max_arrival,
            timing_nodes=nodes,
            critical_path=critical_path,
            num_paths_analyzed=len(constrained),
            slack_histogram=histogram,
            path_pi_to_po=pc["pi_po"],
            path_ff_to_ff=pc["ff_ff"],
            path_ff_to_po=pc["ff_po"],
            path_pi_to_ff=pc["pi_ff"],
        )

    # ── helpers ──────────────────────────────────────────────────────────────
    def _wire_delay(self, circ: Circuit, src: str, dst: str) -> float:
        """Manhattan-distance wire delay using M2 RC model."""
        g_src = circ.gates.get(src)
        g_dst = circ.gates.get(dst)
        if g_src is None or g_dst is None:
            return 0.0
        dx = abs(g_dst.x - g_src.x)
        dy = abs(g_dst.y - g_src.y)
        return (dx + dy) * _WIRE_RC_PS_PER_UNIT

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
        self,
        circ: Circuit,
        nodes: dict[str, TimingNode],
        topo_order: list[str],
    ) -> list[str]:
        # Find endpoint (PO or FF input) with worst slack
        candidates = [
            n for n in circ.primary_outputs
            if n in nodes and nodes[n].required < float("inf")
        ]
        # Also consider FF D inputs
        for ff in circ.flip_flops:
            gate = circ.gates.get(ff)
            if gate:
                for inp in gate.inputs:
                    if inp in nodes and nodes[inp].required < float("inf"):
                        candidates.append(inp)

        if not candidates:
            return []
        endpoint = min(candidates, key=lambda n: nodes[n].slack)

        path = [endpoint]
        current = endpoint
        for _ in range(500):
            gate = circ.gates.get(current)
            if gate is None or gate.is_ff or not gate.inputs:
                break
            # Follow the slowest (highest arrival) input
            worst_inp = max(
                gate.inputs,
                key=lambda i: (
                    nodes[i].arrival if i in nodes else 0.0
                ),
            )
            if worst_inp not in nodes:
                break
            path.append(worst_inp)
            current = worst_inp
        return list(reversed(path))

    def _count_path_types(
        self,
        circ: Circuit,
        nodes: dict[str, TimingNode],
        pi_set: set, ff_set: set, po_set: set,
    ) -> dict[str, int]:
        counts = {"pi_po": 0, "ff_ff": 0, "ff_po": 0, "pi_ff": 0}
        # Heuristic: for each constrained endpoint, check what the critical
        # input source is
        for name, nd in nodes.items():
            if nd.required == float("inf"):
                continue
            is_po = name in po_set
            is_ff_d = any(
                name in (circ.gates[ff].inputs or [])
                for ff in ff_set
                if ff in circ.gates
            )
            if not (is_po or is_ff_d):
                continue
            # Trace back to source
            src = self._find_source(circ, name, pi_set, ff_set)
            if src in pi_set:
                key = "pi_po" if is_po else "pi_ff"
            else:
                key = "ff_po" if is_po else "ff_ff"
            counts[key] += 1
        return counts

    def _find_source(
        self, circ: Circuit, name: str,
        pi_set: set, ff_set: set,
    ) -> str:
        visited: set[str] = set()
        current = name
        for _ in range(200):
            if current in pi_set or current in ff_set:
                return current
            gate = circ.gates.get(current)
            if gate is None or not gate.inputs:
                return current
            # Follow highest-arrival input
            best = max(
                gate.inputs,
                key=lambda i: circ.gates[i].x if i in circ.gates else 0,
            )
            if best in visited:
                break
            visited.add(best)
            current = best
        return current

    def _slack_histogram(
        self, nodes: dict[str, TimingNode]
    ) -> dict[str, int]:
        buckets: dict[str, int] = {
            "< -500ps": 0, "-500~-200ps": 0, "-200~0ps": 0,
            "0~200ps":  0, "200~500ps":  0, "> 500ps":  0,
        }
        for nd in nodes.values():
            s = nd.slack
            if s == float("inf"):
                continue
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
