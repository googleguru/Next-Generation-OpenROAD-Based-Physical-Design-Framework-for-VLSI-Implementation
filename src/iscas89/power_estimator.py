from __future__ import annotations
import math
from dataclasses import dataclass, field

from .bench_parser import Circuit

# ── FreePDK45 power parameters at nominal PVT (1.1 V, 25 °C) ────────────────
# Output node capacitance (fF) — dominant load for dynamic power
_OUTPUT_CAP_FF: dict[str, float] = {
    "INV":  2.0,  "NOT":  2.0,
    "BUFF": 1.2,
    "NAND": 3.0,  "AND":  5.0,   # AND = NAND + INV
    "NOR":  3.0,  "OR":   5.0,
    "XOR":  6.5,  "XNOR": 6.5,
    "DFF":  5.5,               # Q-pin load
}
_OUTPUT_CAP_DEFAULT = 3.0

# Switching activity factor α (fraction of clock cycles the output toggles)
_TOGGLE_RATE: dict[str, float] = {
    "DFF":  0.50,   # FF output toggles ~50% of cycles (register)
    "XOR":  0.25,   "XNOR": 0.25,
    "INV":  0.15,   "NOT":  0.15,  "BUFF": 0.15,
    "NAND": 0.10,   "AND":  0.10,
    "NOR":  0.10,   "OR":   0.10,
}
_TOGGLE_DEFAULT = 0.10

# Leakage current (nA) per gate instance — sub-threshold leakage model
_LEAKAGE_NA: dict[str, float] = {
    "INV":   3.0,  "NOT":  3.0,  "BUFF":  4.0,
    "NAND":  5.0,  "AND":  8.0,
    "NOR":   5.0,  "OR":   8.0,
    "XOR":  10.0,  "XNOR": 10.0,
    "DFF":  18.0,
}
_LEAKAGE_DEFAULT = 5.0

# Wire capacitance contribution from RC extractor (added per net, fF)
_WIRE_CAP_PER_UNIT_FF = 0.076   # fF per cell unit (M2 layer)


@dataclass
class GatePower:
    name:           str
    gtype:          str
    dyn_power_uw:   float   # dynamic power (µW)
    leak_power_nw:  float   # leakage power (nW)
    toggle_rate:    float
    output_cap_ff:  float


@dataclass
class PowerResult:
    circuit_name:        str
    clock_period_ps:     float
    vdd:                 float
    total_dyn_power_uw:  float   # µW
    total_leak_power_nw: float   # nW
    total_power_uw:      float   # µW (dynamic + leakage)
    per_gate:            list[GatePower]
    # Breakdown by gate type
    dyn_by_type:         dict[str, float] = field(default_factory=dict)
    leak_by_type:        dict[str, float] = field(default_factory=dict)
    # Stats
    max_dyn_gate:        str = ""
    max_dyn_uw:          float = 0.0


class PowerEstimator:
    """
    Gate-level dynamic + leakage power estimator.

    P_dynamic   = α × C_L × V_DD² × f
    P_leakage   = I_leak × V_DD (per gate, temperature-independent at 25 °C)
    P_total     = P_dynamic + P_leakage

    Technology: FreePDK45, V_DD = 1.1 V, nominal PVT.
    Wire capacitance is approximated as wire_length × C_per_unit (M2).
    """

    def __init__(
        self,
        clock_period_ps: float = 5000.0,
        vdd: float = 1.1,
    ):
        self.clock_period_ps = clock_period_ps
        self.vdd = vdd
        self.freq_hz = 1e12 / clock_period_ps

    def estimate(self, circ: Circuit, rc_result=None) -> PowerResult:
        """
        Estimate power for all gates in circ.
        If rc_result is provided, wire capacitance from RC extraction
        is added to each gate's output load.
        """
        # Build net-capacitance map from RC result
        net_cap_ff: dict[str, float] = {}
        if rc_result is not None:
            for net in rc_result.nets:
                net_cap_ff[net.name] = net.capacitance_ff

        per_gate: list[GatePower] = []
        dyn_by_type: dict[str, float] = {}
        leak_by_type: dict[str, float] = {}

        for name, gate in circ.gates.items():
            gtype = gate.gtype

            # Output capacitance: intrinsic + wire
            C_out_ff = _OUTPUT_CAP_FF.get(gtype, _OUTPUT_CAP_DEFAULT)
            C_wire_ff = net_cap_ff.get(name, 0.0)
            # Also add wire length estimate (from gate position to nearest sinks)
            wire_len_units = sum(
                abs(gate.x - circ.gates[inp].x) + abs(gate.y - circ.gates[inp].y)
                for inp in (circ.fanout.get(name) or [])
                if inp in circ.gates
            )
            C_wire_ff += wire_len_units * _WIRE_CAP_PER_UNIT_FF
            C_total_ff = C_out_ff + C_wire_ff

            alpha = _TOGGLE_RATE.get(gtype, _TOGGLE_DEFAULT)

            # Dynamic: P = α × C × V² × f  [µW]
            C_F = C_total_ff * 1e-15
            dyn_uw = alpha * C_F * (self.vdd ** 2) * self.freq_hz * 1e6

            # Leakage: I_leak × V_DD  [nW]
            leak_nw = _LEAKAGE_NA.get(gtype, _LEAKAGE_DEFAULT) * self.vdd

            per_gate.append(GatePower(
                name=name, gtype=gtype,
                dyn_power_uw=dyn_uw,
                leak_power_nw=leak_nw,
                toggle_rate=alpha,
                output_cap_ff=C_total_ff,
            ))

            dyn_by_type[gtype] = dyn_by_type.get(gtype, 0.0) + dyn_uw
            leak_by_type[gtype] = leak_by_type.get(gtype, 0.0) + leak_nw

        total_dyn  = sum(g.dyn_power_uw  for g in per_gate)
        total_leak = sum(g.leak_power_nw for g in per_gate)
        total_uw   = total_dyn + total_leak / 1e3   # convert nW → µW

        max_gate = max(per_gate, key=lambda g: g.dyn_power_uw, default=None)

        return PowerResult(
            circuit_name=circ.name,
            clock_period_ps=self.clock_period_ps,
            vdd=self.vdd,
            total_dyn_power_uw=total_dyn,
            total_leak_power_nw=total_leak,
            total_power_uw=total_uw,
            per_gate=per_gate,
            dyn_by_type=dyn_by_type,
            leak_by_type=leak_by_type,
            max_dyn_gate=max_gate.name if max_gate else "",
            max_dyn_uw=max_gate.dyn_power_uw if max_gate else 0.0,
        )
