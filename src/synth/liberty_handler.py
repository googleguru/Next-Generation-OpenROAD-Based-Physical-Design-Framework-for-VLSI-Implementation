from __future__ import annotations
import re
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class LibertyHandler:
    """
    Lightweight Liberty (.lib) parser and validator.
    Extracts cell names, drive strengths, and timing corner info
    without requiring a full EDA toolkit.
    """

    def __init__(self, lib_path: Path):
        self.lib_path = Path(lib_path)
        self._text: str = ""
        self._cells: list[str] = []
        self._parsed = False

    def _ensure_parsed(self) -> None:
        if self._parsed:
            return
        if not self.lib_path.exists():
            logger.error("Liberty file not found: %s", self.lib_path)
            return
        self._text = self.lib_path.read_text(errors="replace")
        self._cells = re.findall(r'cell\s*\(\s*"?(\w+)"?\s*\)', self._text)
        self._parsed = True

    def cell_names(self) -> list[str]:
        self._ensure_parsed()
        return list(self._cells)

    def cell_count(self) -> int:
        self._ensure_parsed()
        return len(self._cells)

    def has_cell(self, name: str) -> bool:
        self._ensure_parsed()
        return name in self._cells

    def operating_conditions(self) -> dict[str, Any]:
        self._ensure_parsed()
        oc: dict[str, Any] = {}
        m = re.search(
            r'operating_conditions\s*\(\s*"?(\w+)"?\s*\)\s*\{([^}]+)\}',
            self._text, re.DOTALL
        )
        if m:
            oc["name"] = m.group(1)
            for kv in re.finditer(r'(\w+)\s*:\s*([\d.eE+-]+)', m.group(2)):
                try:
                    oc[kv.group(1)] = float(kv.group(2))
                except ValueError:
                    oc[kv.group(1)] = kv.group(2)
        return oc

    def validate(self) -> list[str]:
        issues = []
        if not self.lib_path.exists():
            issues.append(f"File not found: {self.lib_path}")
            return issues
        self._ensure_parsed()
        if not self._cells:
            issues.append("No cells found in Liberty file.")
        if "operating_conditions" not in self._text:
            issues.append("No operating_conditions block found.")
        if "wire_load_model" not in self._text:
            issues.append("No wire_load_model found (may affect synthesis QoR).")
        return issues

    def buf_cells(self) -> list[str]:
        self._ensure_parsed()
        return [c for c in self._cells
                if re.match(r"BUF|buf", c, re.I)]

    def inv_cells(self) -> list[str]:
        self._ensure_parsed()
        return [c for c in self._cells
                if re.match(r"INV|inv|NOT", c, re.I)]
