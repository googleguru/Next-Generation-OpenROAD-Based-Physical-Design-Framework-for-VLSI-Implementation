from __future__ import annotations
import datetime
import re
from pathlib import Path
from typing import Any


_RESULTS_SECTION_RE = re.compile(
    r"(<!-- RESULTS_START -->)(.*?)(<!-- RESULTS_END -->)",
    re.DOTALL,
)

_FOOTER_TAG = "<!-- AUTO_UPDATED -->"


class READMEUpdater:
    """
    Updates README.md in-place with fresh experiment results.
    Only the region between <!-- RESULTS_START --> and <!-- RESULTS_END --> is
    replaced; all other content is preserved.
    """

    def __init__(self, readme_path: Path):
        self.readme_path = Path(readme_path)

    def update(
        self,
        flat_rows: list[dict[str, Any]],
        success_rates: dict[str, float],
        selected_figures: list[Path],
        framework_version: str = "1.0.0",
    ) -> None:
        text = self.readme_path.read_text() if self.readme_path.exists() else ""
        block = self._build_block(flat_rows, success_rates,
                                   selected_figures, framework_version)
        if _RESULTS_SECTION_RE.search(text):
            text = _RESULTS_SECTION_RE.sub(
                r"\g<1>" + "\n" + block + "\n" + r"\g<3>", text
            )
        else:
            text = text.rstrip() + f"\n\n<!-- RESULTS_START -->\n{block}\n<!-- RESULTS_END -->\n"

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M UTC")
        if _FOOTER_TAG in text:
            text = re.sub(
                r"<!-- AUTO_UPDATED -->.*",
                f"<!-- AUTO_UPDATED --> *Last updated: {now}*",
                text,
            )
        else:
            text += f"\n{_FOOTER_TAG} *Last updated: {now}*\n"

        self.readme_path.write_text(text)

    def _build_block(
        self,
        flat_rows: list[dict[str, Any]],
        success_rates: dict[str, float],
        figures: list[Path],
        version: str,
    ) -> str:
        now = datetime.datetime.now().strftime("%Y-%m-%d")
        lines: list[str] = [
            f"### Latest Results  *(v{version} · {now})*",
            "",
        ]

        if success_rates:
            lines.append("**Success rates:**")
            for d, r in sorted(success_rates.items()):
                lines.append(f"- {d}: {r:.0%}")
            lines.append("")

        if flat_rows:
            cols = ["design", "wns", "tns", "overflow",
                    "drc_violations", "total_runtime_s"]
            header = " | ".join(cols)
            sep = " | ".join(["---"] * len(cols))
            lines += [f"| {header} |", f"| {sep} |"]
            for row in flat_rows[:20]:
                cells = " | ".join(str(row.get(c, "N/A")) for c in cols)
                lines.append(f"| {cells} |")
            if len(flat_rows) > 20:
                lines.append(f"*… {len(flat_rows) - 20} more rows in REPORT.md*")
            lines.append("")

        for fig in figures[:4]:
            rel = fig.name
            lines.append(f"![{fig.stem}](outputs/figures/{rel})")
            lines.append("")

        return "\n".join(lines)
