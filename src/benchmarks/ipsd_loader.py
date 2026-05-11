from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class IPSDBenchmark:
    name: str
    netlist: Path
    sdc: Path
    pdk: str
    die_area: list[float]
    core_margin: float
    site_name: str
    lib_file: Path
    pdk_lef: Path
    extra_lefs: list[Path] = field(default_factory=list)
    macro_placement: Path | None = None
    target_density: float = 0.70
    clock_period_ns: float = 2.0
    notes: str = ""

    def is_ready(self) -> bool:
        required = [self.netlist, self.sdc, self.lib_file, self.pdk_lef]
        return all(p.exists() for p in required)

    def missing_files(self) -> list[str]:
        checks = {
            "netlist": self.netlist,
            "sdc": self.sdc,
            "lib_file": self.lib_file,
            "pdk_lef": self.pdk_lef,
        }
        for i, lef in enumerate(self.extra_lefs):
            checks[f"extra_lef_{i}"] = lef
        if self.macro_placement:
            checks["macro_placement"] = self.macro_placement
        return [name for name, p in checks.items() if not Path(p).exists()]


class IPSDLoader:
    """
    Loads IPSD benchmark definitions from a YAML manifest.
    Only circuits with all required collateral present are marked as runnable.
    """

    def __init__(self, manifest_path: Path):
        self.manifest_path = Path(manifest_path)
        self._benchmarks: list[IPSDBenchmark] = []
        self._load()

    def _load(self) -> None:
        if not self.manifest_path.exists():
            logger.warning("IPSD manifest not found: %s", self.manifest_path)
            return
        data = yaml.safe_load(self.manifest_path.read_text())
        base_dir = Path(data.get("base_dir", "."))
        for entry in data.get("benchmarks", []):
            bm = self._parse_entry(entry, base_dir)
            self._benchmarks.append(bm)
        logger.info("Loaded %d IPSD benchmark entries", len(self._benchmarks))

    def _parse_entry(self, entry: dict[str, Any], base_dir: Path) -> IPSDBenchmark:
        def resolve(key: str, default: str = "") -> Path:
            v = entry.get(key, default)
            return base_dir / v if v and not Path(v).is_absolute() else Path(v)

        return IPSDBenchmark(
            name=entry["name"],
            netlist=resolve("netlist"),
            sdc=resolve("sdc"),
            pdk=entry.get("pdk", "unknown"),
            die_area=entry.get("die_area", [0, 0, 500, 500]),
            core_margin=entry.get("core_margin", 10.0),
            site_name=entry.get("site_name", "FreePDK45_38x28_10R_NP_162NW_34O"),
            lib_file=resolve("lib_file"),
            pdk_lef=resolve("pdk_lef"),
            extra_lefs=[base_dir / l for l in entry.get("extra_lefs", [])],
            macro_placement=resolve("macro_placement") if entry.get("macro_placement") else None,
            target_density=entry.get("target_density", 0.70),
            clock_period_ns=entry.get("clock_period_ns", 2.0),
            notes=entry.get("notes", ""),
        )

    def runnable(self) -> list[IPSDBenchmark]:
        ready = [b for b in self._benchmarks if b.is_ready()]
        skipped = [b for b in self._benchmarks if not b.is_ready()]
        for b in skipped:
            logger.warning(
                "SKIP %s — missing: %s",
                b.name, ", ".join(b.missing_files())
            )
        return ready

    def all(self) -> list[IPSDBenchmark]:
        return list(self._benchmarks)

    def get(self, name: str) -> IPSDBenchmark | None:
        for b in self._benchmarks:
            if b.name == name:
                return b
        return None
