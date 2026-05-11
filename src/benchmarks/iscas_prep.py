from __future__ import annotations
import logging
import shutil
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ISCASCircuit:
    name: str
    bench_file: Path
    mapped_netlist: Path | None = None
    sdc_file: Path | None = None
    lib_file: Path | None = None
    pdk_lef: Path | None = None
    die_area: list[float] = field(default_factory=lambda: [0, 0, 500, 500])
    core_margin: float = 10.0
    site_name: str = "FreePDK45_38x28_10R_NP_162NW_34O"
    clock_period_ns: float = 5.0
    reason_skipped: str = ""

    def is_synthesized(self) -> bool:
        return (
            self.mapped_netlist is not None and self.mapped_netlist.exists() and
            self.sdc_file is not None and self.sdc_file.exists()
        )


class ISCASPrep:
    """
    Prepares ISCAS benchmark circuits for physical implementation:
    1. Validates .bench / BLIF source availability
    2. Invokes Yosys to synthesize to a target library
    3. Generates a minimal SDC with clock constraints
    4. Flags circuits that cannot be mapped (combinational, no clock, etc.)
    """

    COMBINATIONAL_CIRCUITS = {
        "c17", "c432", "c499", "c880", "c1355",
        "c1908", "c2670", "c3540", "c5315", "c6288", "c7552",
    }

    def __init__(self, manifest_path: Path, work_dir: Path):
        self.manifest_path = Path(manifest_path)
        self.work_dir = Path(work_dir)
        self._circuits: list[ISCASCircuit] = []
        self._load()

    def _load(self) -> None:
        if not self.manifest_path.exists():
            logger.warning("ISCAS manifest not found: %s", self.manifest_path)
            return
        data = yaml.safe_load(self.manifest_path.read_text())
        base_dir = Path(data.get("base_dir", "."))
        lib_file = Path(data.get("lib_file", ""))
        pdk_lef = Path(data.get("pdk_lef", ""))
        for entry in data.get("circuits", []):
            bench = base_dir / entry["bench_file"]
            circ = ISCASCircuit(
                name=entry["name"],
                bench_file=bench,
                lib_file=lib_file,
                pdk_lef=pdk_lef,
                die_area=entry.get("die_area", [0, 0, 500, 500]),
                core_margin=entry.get("core_margin", 10.0),
                site_name=entry.get("site_name",
                                     "FreePDK45_38x28_10R_NP_162NW_34O"),
                clock_period_ns=entry.get("clock_period_ns", 5.0),
            )
            self._circuits.append(circ)

    def prepare_all(self) -> list[ISCASCircuit]:
        results = []
        for circ in self._circuits:
            results.append(self._prepare_one(circ))
        return results

    def _prepare_one(self, circ: ISCASCircuit) -> ISCASCircuit:
        base = circ.name.lower().replace("_", "")
        if base in self.COMBINATIONAL_CIRCUITS:
            circ.reason_skipped = (
                "Purely combinational circuit — no clock domain for physical implementation."
            )
            logger.info("SKIP %s: %s", circ.name, circ.reason_skipped)
            return circ

        if not circ.bench_file.exists():
            circ.reason_skipped = f"Source .bench file not found: {circ.bench_file}"
            logger.warning("SKIP %s: %s", circ.name, circ.reason_skipped)
            return circ

        if circ.lib_file is None or not circ.lib_file.exists():
            circ.reason_skipped = "Liberty file not found — cannot synthesize."
            logger.warning("SKIP %s: %s", circ.name, circ.reason_skipped)
            return circ

        synth_dir = self.work_dir / circ.name
        synth_dir.mkdir(parents=True, exist_ok=True)
        netlist = synth_dir / f"{circ.name}_synth.v"
        sdc = synth_dir / f"{circ.name}.sdc"

        if not netlist.exists():
            success = self._run_yosys(circ, netlist, synth_dir)
            if not success:
                circ.reason_skipped = "Yosys synthesis failed."
                return circ

        self._write_sdc(circ, sdc)
        circ.mapped_netlist = netlist
        circ.sdc_file = sdc
        logger.info("Prepared %s: netlist=%s", circ.name, netlist)
        return circ

    def _run_yosys(self, circ: ISCASCircuit, netlist: Path,
                   work_dir: Path) -> bool:
        if shutil.which("yosys") is None:
            logger.warning("yosys not in PATH — skipping synthesis for %s", circ.name)
            return False
        script = textwrap.dedent(f"""
            read_blif -wideports {circ.bench_file}
            hierarchy -auto-top
            synth -top {circ.name} -flatten
            dfflibmap -liberty {circ.lib_file}
            abc -liberty {circ.lib_file} -script +strash;rewrite;refactor;balance;map
            clean
            write_verilog -noattr {netlist}
        """)
        script_path = work_dir / "synth.ys"
        script_path.write_text(script)
        log_path = work_dir / "yosys.log"
        try:
            with open(log_path, "w") as lf:
                result = subprocess.run(
                    ["yosys", "-q", str(script_path)],
                    stdout=lf, stderr=subprocess.STDOUT,
                    timeout=300, check=False,
                )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.error("Yosys error for %s: %s", circ.name, exc)
            return False

    def _write_sdc(self, circ: ISCASCircuit, sdc_path: Path) -> None:
        content = textwrap.dedent(f"""\
            # Auto-generated SDC for {circ.name}
            create_clock -name clk -period {circ.clock_period_ns} [get_ports clk]
            set_input_delay  -clock clk 0.5 [all_inputs]
            set_output_delay -clock clk 0.5 [all_outputs]
            set_load 0.01 [all_outputs]
        """)
        sdc_path.write_text(content)

    def synthesized(self) -> list[ISCASCircuit]:
        return [c for c in self._circuits if c.is_synthesized()]

    def skipped(self) -> list[tuple[str, str]]:
        return [(c.name, c.reason_skipped)
                for c in self._circuits if c.reason_skipped]
