from __future__ import annotations
import math
from dataclasses import dataclass, field

from .bench_parser import Circuit

# ── FreePDK45 metal stack parameters ─────────────────────────────────────────
# Layer  | R (Ω/μm) | C (fF/μm) | Use
# M1     |   7.70   |   0.250   | local cell-to-cell (≤ 1.5 μm)
# M2     |   4.30   |   0.200   | semi-local (1.5–6 μm)
# M3     |   0.89   |   0.180   | global / long (> 6 μm)
# Via12  |   5.0 Ω                         (M1→M2)
# Via23  |   3.0 Ω                         (M2→M3)
_LAYERS = {
    "M1": (7.70, 0.250),
    "M2": (4.30, 0.200),
    "M3": (0.89, 0.180),
}
_VIA_R = {"M1M2": 5.0, "M2M3": 3.0}

# 1 cell unit = 380 nm (FreePDK45 site width)
_UNIT_TO_UM = 0.38

# Breakpoints (μm) for routing layer selection
_M1_CUTOFF = 1.5   # ≤ 1.5 μm → M1
_M2_CUTOFF = 6.0   # ≤ 6 μm  → M2, else M3

# ── Gate-type output driver resistance (Ω) ───────────────────────────────────
# Extracted from FreePDK45 liberty file (NAND2X1 drive-strength)
# Represents the pull-up/pull-down equivalent resistance for the slowest arc
_DRIVER_RES: dict[str, float] = {
    "INV":  750,  "NOT":  750,
    "BUFF": 180,
    "NAND": 900,  "AND": 1400,   # AND2 = NAND2+INV in series
    "NOR":  1100, "OR":  1350,
    "XOR":  1800, "XNOR": 1800,
    "DFF":  400,               # Q-output driver
}
_DRIVER_RES_DEFAULT = 1000.0

# Fanout degradation: each additional sink adds ~10% to effective driver R
_FANOUT_R_FACTOR = 0.10

# Typical cell input capacitance (fF) — gate input load
_INPUT_CAP_FF: dict[str, float] = {
    "INV": 1.8, "NOT": 1.8, "BUFF": 1.2,
    "NAND": 2.2, "AND": 2.2, "NOR": 2.2, "OR": 2.2,
    "XOR": 3.5, "XNOR": 3.5,
    "DFF": 4.0,
}
_INPUT_CAP_DEFAULT = 2.0


@dataclass
class NetRC:
    name:             str
    routing_layer:    str          # M1 / M2 / M3
    length_units:     float
    length_um:        float
    driver_res_ohms:  float
    wire_res_ohms:    float
    capacitance_ff:   float        # wire + load caps
    elmore_delay_ps:  float
    num_sinks:        int
    fanout:           int


@dataclass
class LayerStats:
    layer:          str
    net_count:      int
    total_length_um: float
    total_res_kohm:  float
    total_cap_ff:    float


@dataclass
class RCResult:
    circuit_name:            str
    nets:                    list[NetRC]
    total_wirelength_um:     float
    total_resistance_kohm:   float
    total_capacitance_ff:    float
    max_elmore_delay_ps:     float
    avg_elmore_delay_ps:     float
    top_critical_nets:       list[str]
    layer_stats:             list[LayerStats]
    estimated_power_uw:      float   # rough dynamic power from RC (µW)


class RCExtractor:
    """
    Physically-calibrated lumped RC extraction.

    Improvements over the baseline:
    - Gate-type-specific driver resistance (liberty-like table)
    - Three-layer wire model (M1/M2/M3) selected by wire length
    - Via resistance between routing layers
    - Fanout-dependent driver resistance degradation
    - Per-layer aggregate statistics
    - Rough dynamic power estimate: P ≈ Σ α × C_net × V² × f
    """

    def __init__(
        self,
        clock_period_ps: float = 5000.0,
        vdd: float = 1.1,          # V — FreePDK45 nominal
        toggle_rate: float = 0.10,  # default switching activity
    ):
        self.clock_freq_hz = 1e12 / clock_period_ps  # Hz
        self.vdd = vdd
        self.toggle_rate = toggle_rate

    # ── public ───────────────────────────────────────────────────────────────
    def extract(self, circ: Circuit) -> RCResult:
        nets: list[NetRC] = []

        for name, gate in circ.gates.items():
            # Collect sinks that are other gates
            sinks = [circ.gates[inp] for inp in gate.inputs if inp in circ.gates]
            if not sinks:
                # No internal connections: still count the gate output net
                sinks = []

            # Total Manhattan wirelength (Steiner tree approximation)
            length_um = sum(
                (abs(gate.x - s.x) + abs(gate.y - s.y)) * _UNIT_TO_UM
                for s in sinks
            )

            fanout = max(1, len(sinks))

            # Select routing layer by wire length
            layer = self._select_layer(length_um)
            r_per_um, c_per_um = _LAYERS[layer]
            via_r = self._via_resistance(layer)

            # Driver resistance with fanout penalty
            r_drv = _DRIVER_RES.get(gate.gtype, _DRIVER_RES_DEFAULT)
            r_drv *= 1.0 + _FANOUT_R_FACTOR * (fanout - 1)

            # Wire parasitics
            R_wire = length_um * r_per_um + via_r
            C_wire = length_um * c_per_um          # fF

            # Load capacitance: sum of sink input caps
            C_loads = sum(
                _INPUT_CAP_FF.get(s.gtype, _INPUT_CAP_DEFAULT)
                for s in sinks
            ) or _INPUT_CAP_DEFAULT

            # Elmore delay: τ = (R_drv + R_wire/2) × (C_wire + C_loads) [ps]
            R_eff  = r_drv + R_wire / 2.0
            C_total_fF = C_wire + C_loads
            elmore_ps  = R_eff * (C_total_fF * 1e-15) * 1e12

            nets.append(NetRC(
                name=name,
                routing_layer=layer,
                length_units=length_um / _UNIT_TO_UM,
                length_um=length_um,
                driver_res_ohms=r_drv,
                wire_res_ohms=R_wire,
                capacitance_ff=C_total_fF,
                elmore_delay_ps=elmore_ps,
                num_sinks=len(sinks),
                fanout=fanout,
            ))

        if not nets:
            return RCResult(circ.name, [], 0, 0, 0, 0, 0, [], [], 0.0)

        total_wl  = sum(n.length_um for n in nets)
        total_r   = sum(n.wire_res_ohms for n in nets) / 1e3
        total_c   = sum(n.capacitance_ff for n in nets)
        delays    = [n.elmore_delay_ps for n in nets]
        max_delay = max(delays)
        avg_delay = sum(delays) / len(delays)

        sorted_nets   = sorted(nets, key=lambda n: n.elmore_delay_ps, reverse=True)
        top_nets      = [n.name for n in sorted_nets[:10]]
        layer_stats   = self._layer_statistics(nets)

        # Dynamic power estimate: P = α × C × V² × f  (summed over all nets)
        total_C_F = total_c * 1e-15
        power_uw  = (
            self.toggle_rate * total_C_F * (self.vdd ** 2) * self.clock_freq_hz
            * 1e6
        )

        return RCResult(
            circuit_name=circ.name,
            nets=nets,
            total_wirelength_um=total_wl,
            total_resistance_kohm=total_r,
            total_capacitance_ff=total_c,
            max_elmore_delay_ps=max_delay,
            avg_elmore_delay_ps=avg_delay,
            top_critical_nets=top_nets,
            layer_stats=layer_stats,
            estimated_power_uw=power_uw,
        )

    # ── helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _select_layer(length_um: float) -> str:
        if length_um <= _M1_CUTOFF:
            return "M1"
        if length_um <= _M2_CUTOFF:
            return "M2"
        return "M3"

    @staticmethod
    def _via_resistance(layer: str) -> float:
        if layer == "M2":
            return _VIA_R["M1M2"]
        if layer == "M3":
            return _VIA_R["M1M2"] + _VIA_R["M2M3"]
        return 0.0

    @staticmethod
    def _layer_statistics(nets: list[NetRC]) -> list[LayerStats]:
        stats: dict[str, LayerStats] = {}
        for n in nets:
            s = stats.setdefault(
                n.routing_layer,
                LayerStats(n.routing_layer, 0, 0.0, 0.0, 0.0),
            )
            s.net_count      += 1
            s.total_length_um += n.length_um
            s.total_res_kohm  += n.wire_res_ohms / 1e3
            s.total_cap_ff    += n.capacitance_ff
        return sorted(stats.values(), key=lambda s: s.layer)
