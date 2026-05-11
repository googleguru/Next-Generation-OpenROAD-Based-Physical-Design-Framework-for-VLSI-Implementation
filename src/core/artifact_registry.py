from __future__ import annotations
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .state_model import FlowStage


@dataclass
class Artifact:
    name: str
    path: Path
    stage: FlowStage
    kind: str  # "netlist", "def", "odb", "sdc", "rpt", "log", "verilog"
    size_bytes: int = 0
    checksum: str = ""

    def exists(self) -> bool:
        return self.path.exists()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": str(self.path),
            "stage": self.stage.value,
            "kind": self.kind,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
        }


class ArtifactRegistry:
    _STAGE_OUTPUTS: dict[FlowStage, list[str]] = {
        FlowStage.SYNTHESIS:     ["synth.v", "synth.sdc"],
        FlowStage.FLOORPLAN:     ["floorplan.odb", "floorplan.def"],
        FlowStage.PDN:           ["pdn.odb", "pdn.def"],
        FlowStage.GLOBAL_PLACE:  ["gplace.odb", "gplace.def"],
        FlowStage.DETAIL_PLACE:  ["dplace.odb", "dplace.def"],
        FlowStage.CTS:           ["cts.odb", "cts.def", "cts.sdc"],
        FlowStage.GLOBAL_ROUTE:  ["groute.odb", "groute.def"],
        FlowStage.DETAIL_ROUTE:  ["droute.odb", "droute.def"],
        FlowStage.FINISH:        ["final.odb", "final.def", "final.gds",
                                   "final_timing.rpt", "final_drc.rpt"],
    }

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self._registry: dict[str, Artifact] = {}

    def register(self, stage: FlowStage, filename: str, kind: str) -> Artifact:
        stage_dir = self.work_dir / stage.value
        stage_dir.mkdir(parents=True, exist_ok=True)
        path = stage_dir / filename
        size = path.stat().st_size if path.exists() else 0
        art = Artifact(name=filename, path=path, stage=stage,
                       kind=kind, size_bytes=size)
        key = f"{stage.value}/{filename}"
        self._registry[key] = art
        return art

    def get(self, stage: FlowStage, filename: str) -> Optional[Artifact]:
        return self._registry.get(f"{stage.value}/{filename}")

    def latest_odb(self, up_to_stage: FlowStage) -> Optional[Path]:
        order = FlowStage.ordered()
        idx = order.index(up_to_stage)
        for stage in reversed(order[: idx + 1]):
            candidates = self._STAGE_OUTPUTS.get(stage, [])
            for name in candidates:
                if name.endswith(".odb"):
                    key = f"{stage.value}/{name}"
                    art = self._registry.get(key)
                    if art and art.exists():
                        return art.path
        return None

    def stage_dir(self, stage: FlowStage) -> Path:
        d = self.work_dir / stage.value
        d.mkdir(parents=True, exist_ok=True)
        return d

    def expected_outputs(self, stage: FlowStage) -> list[Path]:
        return [
            self.work_dir / stage.value / fname
            for fname in self._STAGE_OUTPUTS.get(stage, [])
        ]

    def snapshot(self, stage: FlowStage, dest: Path) -> None:
        src = self.work_dir / stage.value
        if src.exists():
            shutil.copytree(src, dest / stage.value, dirs_exist_ok=True)

    def restore_snapshot(self, stage: FlowStage, snapshot_dir: Path) -> bool:
        src = snapshot_dir / stage.value
        dest = self.work_dir / stage.value
        if not src.exists():
            return False
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
        return True

    def dump_manifest(self, path: Path) -> None:
        data = {k: v.to_dict() for k, v in self._registry.items()}
        path.write_text(json.dumps(data, indent=2))

    def load_manifest(self, path: Path) -> None:
        if not path.exists():
            return
        data = json.loads(path.read_text())
        for key, entry in data.items():
            stage = FlowStage(entry["stage"])
            art = Artifact(
                name=entry["name"],
                path=Path(entry["path"]),
                stage=stage,
                kind=entry["kind"],
                size_bytes=entry.get("size_bytes", 0),
            )
            self._registry[key] = art
