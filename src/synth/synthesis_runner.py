from __future__ import annotations
import logging
import shutil
import subprocess
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SynthesisResult:
    design_name: str
    netlist_path: Path | None
    sdc_path: Path | None
    cell_count: int = 0
    success: bool = False
    log_path: Path | None = None
    error_msg: str = ""


class SynthesisRunner:
    """
    Drives Yosys synthesis for designs that require RTL-to-gate mapping
    before entering the physical implementation flow.
    Supports Verilog and BLIF input formats.
    """

    def __init__(
        self,
        lib_file: Path,
        work_dir: Path,
        yosys_binary: str = "yosys",
        timeout_s: int = 600,
    ):
        self.lib_file = Path(lib_file)
        self.work_dir = Path(work_dir)
        self.yosys_binary = yosys_binary
        self.timeout_s = timeout_s

    def run(
        self,
        design_name: str,
        rtl_files: list[Path],
        top_module: str = "",
        clock_period_ns: float = 5.0,
        input_format: str = "verilog",  # "verilog" | "blif"
        abc_script: str = "+strash;rewrite;refactor;balance;map",
    ) -> SynthesisResult:
        if shutil.which(self.yosys_binary) is None:
            msg = f"Yosys binary '{self.yosys_binary}' not found in PATH."
            logger.error(msg)
            return SynthesisResult(design_name=design_name,
                                    netlist_path=None, sdc_path=None,
                                    success=False, error_msg=msg)

        out_dir = self.work_dir / design_name
        out_dir.mkdir(parents=True, exist_ok=True)
        netlist = out_dir / f"{design_name}_synth.v"
        sdc = out_dir / f"{design_name}.sdc"
        script_path = out_dir / "synth.ys"
        log_path = out_dir / "yosys.log"

        script = self._build_script(
            design_name, rtl_files, top_module,
            netlist, input_format, abc_script
        )
        script_path.write_text(script)
        self._write_sdc(design_name, clock_period_ns, sdc)

        try:
            with open(log_path, "w") as lf:
                result = subprocess.run(
                    [self.yosys_binary, "-q", str(script_path)],
                    stdout=lf, stderr=subprocess.STDOUT,
                    timeout=self.timeout_s, check=False,
                )
            success = result.returncode == 0 and netlist.exists()
        except subprocess.TimeoutExpired:
            msg = f"Yosys timed out after {self.timeout_s}s"
            logger.error(msg)
            return SynthesisResult(design_name=design_name,
                                    netlist_path=None, sdc_path=sdc,
                                    success=False, log_path=log_path,
                                    error_msg=msg)
        except FileNotFoundError as exc:
            return SynthesisResult(design_name=design_name,
                                    netlist_path=None, sdc_path=sdc,
                                    success=False, error_msg=str(exc))

        cell_count = 0
        if netlist.exists():
            cell_count = netlist.read_text(errors="replace").count("(")

        return SynthesisResult(
            design_name=design_name,
            netlist_path=netlist if success else None,
            sdc_path=sdc,
            cell_count=cell_count,
            success=success,
            log_path=log_path,
            error_msg="" if success else "Yosys returned non-zero exit code",
        )

    def _build_script(
        self,
        design_name: str,
        rtl_files: list[Path],
        top_module: str,
        netlist: Path,
        fmt: str,
        abc_script: str,
    ) -> str:
        reads = "\n".join(
            (f"read_blif -wideports {f}" if fmt == "blif" else f"read_verilog {f}")
            for f in rtl_files
        )
        top = f"-top {top_module}" if top_module else "-auto-top"
        return textwrap.dedent(f"""
            {reads}
            hierarchy {top}
            synth -flatten
            dfflibmap -liberty {self.lib_file}
            abc -liberty {self.lib_file} -script "{abc_script}"
            clean
            write_verilog -noattr {netlist}
        """).strip()

    def _write_sdc(self, design_name: str, period_ns: float, sdc: Path) -> None:
        sdc.write_text(textwrap.dedent(f"""\
            # SDC generated for {design_name}
            create_clock -name clk -period {period_ns} [get_ports clk]
            set_input_delay  -clock clk [expr {{{period_ns}*0.2}}] [all_inputs]
            set_output_delay -clock clk [expr {{{period_ns}*0.2}}] [all_outputs]
        """))
