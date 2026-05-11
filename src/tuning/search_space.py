from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Union
import yaml
from pathlib import Path

Numeric = Union[int, float]


@dataclass
class Parameter:
    name: str
    ptype: str           # "float" | "int" | "choice"
    low: Numeric = 0
    high: Numeric = 1
    step: Numeric = 0
    choices: list[Any] = field(default_factory=list)
    default: Any = None
    description: str = ""

    def clip(self, value: Numeric) -> Numeric:
        if self.ptype == "choice":
            return value if value in self.choices else self.choices[0]
        lo = float(self.low)
        hi = float(self.high)
        v = max(lo, min(hi, float(value)))
        if self.ptype == "int":
            return int(round(v))
        return v

    def random_sample(self, rng: Any) -> Any:
        if self.ptype == "choice":
            return rng.choice(self.choices)
        lo, hi = float(self.low), float(self.high)
        v = rng.uniform(lo, hi)
        if self.ptype == "int":
            return int(round(v))
        if self.step > 0:
            v = round(v / float(self.step)) * float(self.step)
        return round(v, 6)


class SearchSpace:
    def __init__(self, params: list[Parameter] | None = None):
        self._params: dict[str, Parameter] = {}
        for p in (params or []):
            self._params[p.name] = p

    def add(self, param: Parameter) -> None:
        self._params[param.name] = param

    def get(self, name: str) -> Parameter | None:
        return self._params.get(name)

    def defaults(self) -> dict[str, Any]:
        return {p.name: p.default for p in self._params.values()}

    def sample(self, rng: Any) -> dict[str, Any]:
        return {name: p.random_sample(rng) for name, p in self._params.items()}

    def clip_all(self, params: dict[str, Any]) -> dict[str, Any]:
        clipped = {}
        for name, val in params.items():
            p = self._params.get(name)
            clipped[name] = p.clip(val) if p else val
        return clipped

    @classmethod
    def from_yaml(cls, path: Path) -> "SearchSpace":
        data = yaml.safe_load(Path(path).read_text())
        params = []
        for entry in data.get("parameters", []):
            params.append(Parameter(
                name=entry["name"],
                ptype=entry["type"],
                low=entry.get("low", 0),
                high=entry.get("high", 1),
                step=entry.get("step", 0),
                choices=entry.get("choices", []),
                default=entry.get("default"),
                description=entry.get("description", ""),
            ))
        return cls(params)

    def __len__(self) -> int:
        return len(self._params)

    def names(self) -> list[str]:
        return list(self._params.keys())
