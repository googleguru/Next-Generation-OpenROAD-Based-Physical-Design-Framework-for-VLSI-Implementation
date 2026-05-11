from __future__ import annotations
import math
from dataclasses import dataclass, field

from .bench_parser import Circuit


# Technology parameters (45nm-like unit model)
_WIRE_RES_PER_UM   = 0.08    # Ω/μm (M3 typical)
_WIRE_CAP_PER_UM   = 0.18e-15  # F/μm (M3 coupling + ground cap)
_UNIT_TO_UM        = 0.38    # 1 cell unit = 380 nm (FreePDK45 site width)
_DRIVER_RES_OHMS   = 500.0   # typical cell driver resistance
_LOAD_CAP_PF       = 0.004   # typical cell input cap (pF)


@dataclass
class NetRC:
    name: str           # driving gate
    length_units: float
    length_um: float
    resistance_ohms: float
    capacitance_ff: float
    elmore_delay_ps: float
    num_sinks: int


@dataclass
class RCResult:
    circuit_name: str
    nets: list[NetRC]
    total_wirelength_um: float
    total_resistance_kohm: float
    total_capacitance_ff: float
    max_elmore_delay_ps: float
    avg_elmore_delay_ps: float
    top_critical_nets: list[str]    # sorted by Elmore delay


class RCExtractor:
    """
    Lumped RC extraction using Manhattan wire length from placed coordinates.
    Computes Elmore delay for each net: τ = (R_driver + R_wire/2) × (C_wire + C_loads)
    """

    def extract(self, circ: Circuit) -> RCResult:
        nets: list[NetRC] = []
        for name, gate in circ.gates.items():
            if not gate.inputs:
                continue
            sinks = [
                circ.gates[inp]
                for inp in gate.inputs
                if inp in circ.gates
            ]
            # Total Manhattan length from driver to all sinks (Steiner tree approximation)
            total_length = 0.0
            for sink in sinks:
                dx = abs(gate.x - sink.x)
                dy = abs(gate.y - sink.y)
                total_length += (dx + dy) * _UNIT_TO_UM  # in μm

            num_sinks = max(1, len(sinks))
            length_um = total_length
            R_wire = length_um * _WIRE_RES_PER_UM
            C_wire = length_um * _WIRE_CAP_PER_UM * 1e15  # convert to fF
            C_loads = num_sinks * _LOAD_CAP_PF * 1e3  # convert to fF

            # Elmore delay: τ = (R_driver + R_wire/2) × (C_wire + C_loads)
            R_total = _DRIVER_RES_OHMS + R_wire / 2.0
            C_total = (C_wire + C_loads) * 1e-15  # back to Farads
            elmore_ps = R_total * C_total * 1e12  # in ps

            nets.append(NetRC(
                name=name,
                length_units=total_length / _UNIT_TO_UM,
                length_um=length_um,
                resistance_ohms=R_wire,
                capacitance_ff=C_wire + C_loads,
                elmore_delay_ps=elmore_ps,
                num_sinks=num_sinks,
            ))

        if not nets:
            return RCResult(circ.name, [], 0, 0, 0, 0, 0, [])

        total_wl = sum(n.length_um for n in nets)
        total_r = sum(n.resistance_ohms for n in nets) / 1e3
        total_c = sum(n.capacitance_ff for n in nets)
        delays = [n.elmore_delay_ps for n in nets]
        max_delay = max(delays)
        avg_delay = sum(delays) / len(delays)

        sorted_nets = sorted(nets, key=lambda n: n.elmore_delay_ps, reverse=True)
        top_nets = [n.name for n in sorted_nets[:10]]

        return RCResult(
            circuit_name=circ.name,
            nets=nets,
            total_wirelength_um=total_wl,
            total_resistance_kohm=total_r,
            total_capacitance_ff=total_c,
            max_elmore_delay_ps=max_delay,
            avg_elmore_delay_ps=avg_delay,
            top_critical_nets=top_nets,
        )
