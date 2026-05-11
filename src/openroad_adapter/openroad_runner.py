from __future__ import annotations
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..core.state_model import FlowStage
from .metrics_extractor import MetricsExtractor

logger = logging.getLogger(__name__)

TCL_TEMPLATE_DIR = Path(__file__).parent / "tcl_templates"

STAGE_TCL_MAP: dict[FlowStage, str] = {
    FlowStage.FLOORPLAN:     "floorplan.tcl",
    FlowStage.PDN:           "pdn.tcl",
    FlowStage.GLOBAL_PLACE:  "global_place.tcl",
    FlowStage.DETAIL_PLACE:  "detail_place.tcl",
    FlowStage.CTS:           "cts.tcl",
    FlowStage.GLOBAL_ROUTE:  "global_route.tcl",
    FlowStage.DETAIL_ROUTE:  "detail_route.tcl",
    FlowStage.FINISH:        "finish.tcl",
}


class EDARunnerError(Exception):
    pass


class EDARunner:
    """Thin wrapper that renders a Tcl template and invokes the EDA binary."""

    def __init__(
        self,
        binary: str = "openroad",
        extra_args: list[str] | None = None,
        timeout_s: int = 3600,
        env_extra: dict[str, str] | None = None,
    ):
        self.binary = binary
        self.extra_args = extra_args or []
        self.timeout_s = timeout_s
        self.env_extra = env_extra or {}
        self._jinja = Environment(
            loader=FileSystemLoader(str(TCL_TEMPLATE_DIR)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.extractor = MetricsExtractor()

    def _find_binary(self) -> str:
        found = shutil.which(self.binary)
        if found:
            return found
        alt = shutil.which("openroad")
        if alt:
            return alt
        raise EDARunnerError(
            f"EDA binary '{self.binary}' not found in PATH. "
            "Install OpenROAD or set EDA_BINARY env variable."
        )

    def execute(
        self,
        stage: FlowStage,
        params: dict[str, Any],
        work_dir: Path,
    ) -> dict[str, Any]:
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

        tcl_template = STAGE_TCL_MAP.get(stage)
        if tcl_template is None:
            raise EDARunnerError(f"No Tcl template registered for stage {stage.value}")

        tcl_script = self._render(tcl_template, params, work_dir)
        script_path = work_dir / f"{stage.value}.tcl"
        script_path.write_text(tcl_script)

        log_path = work_dir / "stage.log"
        self._invoke(script_path, log_path)

        metrics = self.extractor.extract(stage, work_dir, log_path)
        return metrics

    def _render(self, template_name: str, params: dict[str, Any],
                work_dir: Path) -> str:
        try:
            tpl = self._jinja.get_template(template_name)
        except Exception as exc:
            raise EDARunnerError(f"Template load error {template_name}: {exc}") from exc
        ctx = dict(params)
        ctx["work_dir"] = str(work_dir)
        try:
            return tpl.render(**ctx)
        except Exception as exc:
            raise EDARunnerError(f"Template render error {template_name}: {exc}") from exc

    def _invoke(self, script: Path, log_path: Path) -> None:
        binary = self._find_binary()
        cmd = [binary, "-no_splash", "-exit"] + self.extra_args + [str(script)]
        env = {**os.environ, **self.env_extra}

        logger.debug("Running: %s", " ".join(cmd))
        with open(log_path, "w") as log_fh:
            try:
                result = subprocess.run(
                    cmd,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    env=env,
                    timeout=self.timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise EDARunnerError(
                    f"EDA run timed out after {self.timeout_s}s for {script}"
                )
            except FileNotFoundError as exc:
                raise EDARunnerError(f"Binary not found: {exc}") from exc

        if result.returncode != 0:
            tail = self._tail_log(log_path, 40)
            raise EDARunnerError(
                f"EDA exited with code {result.returncode}.\n"
                f"Last log lines:\n{tail}"
            )

    @staticmethod
    def _tail_log(path: Path, n: int = 40) -> str:
        if not path.exists():
            return ""
        lines = path.read_text(errors="replace").splitlines()
        return "\n".join(lines[-n:])


class SynthesisHandoffExecutor:
    """Validates and copies synthesis outputs into the flow work directory."""

    def execute(
        self,
        stage: FlowStage,
        params: dict[str, Any],
        work_dir: Path,
    ) -> dict[str, Any]:
        netlist = Path(params.get("synth_netlist", ""))
        sdc = Path(params.get("synth_sdc", ""))
        if not netlist.exists():
            from ..core.stage_runner import StageRunnerError
            raise StageRunnerError(f"Synthesis netlist not found: {netlist}")
        if not sdc.exists():
            from ..core.stage_runner import StageRunnerError
            raise StageRunnerError(f"Synthesis SDC not found: {sdc}")
        dest = Path(work_dir)
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(netlist, dest / "synth.v")
        shutil.copy2(sdc, dest / "synth.sdc")
        logger.info("Synthesis handoff: netlist=%s sdc=%s", netlist, sdc)
        return {"synth_cells": _count_cells(dest / "synth.v")}


def _count_cells(netlist_path: Path) -> int:
    try:
        text = netlist_path.read_text(errors="replace")
        return text.count("(")
    except Exception:
        return 0
