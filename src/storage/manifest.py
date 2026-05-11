from __future__ import annotations
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RunManifest:
    run_id: str
    design_name: str
    seed: int
    framework_version: str
    timestamp: float = field(default_factory=time.time)
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    git_sha: str = ""
    tags: list[str] = field(default_factory=list)

    def save(self, path: Path) -> None:
        Path(path).write_text(
            json.dumps(asdict(self), indent=2, default=str)
        )

    @classmethod
    def load(cls, path: Path) -> "RunManifest":
        data = json.loads(Path(path).read_text())
        return cls(**data)

    @staticmethod
    def capture_git_sha() -> str:
        try:
            import subprocess
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            return ""
