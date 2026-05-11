from __future__ import annotations
from pathlib import Path
from typing import Any


class DatasetNormalizer:
    """
    Converts heterogeneous benchmark specs (IPSD, ISCAS, custom) into a
    unified flat config dict that FlowController and ArtifactRegistry understand.
    """

    def from_ipsd(self, bm: Any) -> dict[str, Any]:
        return {
            "design_name": bm.name,
            "synth_netlist": str(bm.netlist),
            "synth_sdc": str(bm.sdc),
            "pdk": bm.pdk,
            "die_area_x": bm.die_area[2],
            "die_area_y": bm.die_area[3],
            "core_margin": bm.core_margin,
            "site_name": bm.site_name,
            "lib_file": str(bm.lib_file),
            "pdk_lef": str(bm.pdk_lef),
            "extra_lefs": [str(l) for l in bm.extra_lefs],
            "macro_placement_file": str(bm.macro_placement) if bm.macro_placement else None,
            "target_density": bm.target_density,
            "clock_period_ns": bm.clock_period_ns,
        }

    def from_iscas(self, circ: Any) -> dict[str, Any] | None:
        if not circ.is_synthesized():
            return None
        return {
            "design_name": circ.name,
            "synth_netlist": str(circ.mapped_netlist),
            "synth_sdc": str(circ.sdc_file),
            "pdk": "nangate45",
            "die_area_x": circ.die_area[2],
            "die_area_y": circ.die_area[3],
            "core_margin": circ.core_margin,
            "site_name": circ.site_name,
            "lib_file": str(circ.lib_file) if circ.lib_file else "",
            "pdk_lef": str(circ.pdk_lef) if circ.pdk_lef else "",
            "extra_lefs": [],
            "macro_placement_file": None,
            "target_density": 0.70,
            "clock_period_ns": circ.clock_period_ns,
        }

    def normalize_list(self, benchmarks: list[Any], source: str) -> list[dict[str, Any]]:
        out = []
        for bm in benchmarks:
            if source == "ipsd":
                cfg = self.from_ipsd(bm)
            elif source == "iscas":
                cfg = self.from_iscas(bm)
                if cfg is None:
                    continue
            else:
                raise ValueError(f"Unknown benchmark source: {source}")
            out.append(cfg)
        return out
