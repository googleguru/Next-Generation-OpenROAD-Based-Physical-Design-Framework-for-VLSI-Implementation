from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    name: str
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def report(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        lines = [f"[{status}] {self.name}"]
        for e in self.errors:
            lines.append(f"  ERROR  : {e}")
        for w in self.warnings:
            lines.append(f"  WARN   : {w}")
        return "\n".join(lines)


class CollateralValidator:
    """Validates all required input files before a flow run starts."""

    REQUIRED_KEYS = ["netlist", "sdc", "lib_file", "pdk_lef"]

    def validate(self, name: str, config: dict[str, Any]) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        for key in self.REQUIRED_KEYS:
            val = config.get(key)
            if not val:
                errors.append(f"Missing required field: {key}")
                continue
            p = Path(val)
            if not p.exists():
                errors.append(f"{key} not found: {p}")
            elif p.stat().st_size == 0:
                errors.append(f"{key} is empty: {p}")

        for i, lef in enumerate(config.get("extra_lefs", [])):
            p = Path(lef)
            if not p.exists():
                warnings.append(f"extra_lef[{i}] not found: {p}")

        if config.get("macro_placement"):
            mp = Path(config["macro_placement"])
            if not mp.exists():
                warnings.append(f"macro_placement file not found: {mp}")

        die_area = config.get("die_area", [])
        if len(die_area) != 4:
            errors.append(f"die_area must have 4 values [x0 y0 x1 y1], got: {die_area}")
        elif die_area[2] <= die_area[0] or die_area[3] <= die_area[1]:
            errors.append(f"die_area dimensions non-positive: {die_area}")

        cp = config.get("clock_period_ns", 0)
        if cp <= 0:
            errors.append(f"clock_period_ns must be positive, got: {cp}")

        passed = len(errors) == 0
        result = ValidationResult(name=name, passed=passed,
                                   errors=errors, warnings=warnings)
        if not passed:
            logger.error("Validation FAILED for %s:\n%s", name, result.report())
        elif warnings:
            logger.warning("Validation warnings for %s:\n%s", name, result.report())
        return result

    def validate_many(
        self, entries: list[tuple[str, dict[str, Any]]]
    ) -> list[ValidationResult]:
        return [self.validate(name, cfg) for name, cfg in entries]
