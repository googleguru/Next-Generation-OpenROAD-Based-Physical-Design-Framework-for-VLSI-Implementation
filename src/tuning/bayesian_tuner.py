from __future__ import annotations
import logging
import math
import random
from typing import Any

from ..core.state_model import FlowStage
from .search_space import SearchSpace

logger = logging.getLogger(__name__)


class _GaussianProcess:
    """Lightweight GP surrogate using RBF kernel — no external ML deps required."""

    def __init__(self, length_scale: float = 1.0, noise: float = 1e-4):
        self.length_scale = length_scale
        self.noise = noise
        self._X: list[list[float]] = []
        self._y: list[float] = []

    def _rbf(self, a: list[float], b: list[float]) -> float:
        dist2 = sum((x - y) ** 2 for x, y in zip(a, b))
        return math.exp(-0.5 * dist2 / (self.length_scale ** 2))

    def fit(self, X: list[list[float]], y: list[float]) -> None:
        self._X = X
        self._y = y

    def predict(self, x: list[float]) -> tuple[float, float]:
        if not self._X:
            return 0.0, 1.0
        k = [self._rbf(x, xi) for xi in self._X]
        K = [[self._rbf(xi, xj) for xj in self._X] for xi in self._X]
        n = len(K)
        for i in range(n):
            K[i][i] += self.noise
        try:
            alpha = _solve(K, self._y)
        except Exception:
            return 0.0, 1.0
        mu = sum(kv * av for kv, av in zip(k, alpha))
        var = max(0.0, 1.0 - sum(kv * sum(K[i][j] * kv2
                                           for j, kv2 in enumerate(k))
                                  for i, kv in enumerate(k)))
        return mu, math.sqrt(var)


def _solve(A: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    M = [row[:] + [bv] for row, bv in zip(A, b)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(M[r][col]))
        M[col], M[pivot] = M[pivot], M[col]
        if abs(M[col][col]) < 1e-12:
            continue
        for row in range(col + 1, n):
            factor = M[row][col] / M[col][col]
            M[row] = [M[row][j] - factor * M[col][j] for j in range(n + 1)]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = (M[i][n] - sum(M[i][j] * x[j] for j in range(i + 1, n))) / M[i][i]
    return x


class BayesianTuner:
    """
    Upper-Confidence-Bound Bayesian optimiser with a lightweight built-in GP.
    Falls back gracefully if scikit-optimize is not installed.
    """

    def __init__(
        self,
        space: SearchSpace,
        objective: str = "wns",
        n_initial: int = 5,
        kappa: float = 2.576,
        seed: int = 42,
    ):
        self.space = space
        self.objective = objective
        self.n_initial = n_initial
        self.kappa = kappa
        self._rng = random.Random(seed)
        self._gp = _GaussianProcess()
        self._obs_X: list[list[float]] = []
        self._obs_y: list[float] = []
        self._call_count = 0
        self._best_params: dict[str, Any] = space.defaults()
        self._best_score: float = -1e9

    def _encode(self, params: dict[str, Any]) -> list[float]:
        vec = []
        for name in self.space.names():
            p = self.space.get(name)
            v = params.get(name, p.default if p else 0)
            if p and p.ptype == "choice":
                vec.append(float(p.choices.index(v)) if v in p.choices else 0.0)
            else:
                lo, hi = float(p.low), float(p.high)
                vec.append((float(v) - lo) / (hi - lo + 1e-9) if p else 0.0)
        return vec

    def observe(self, params: dict[str, Any], metrics: dict[str, Any]) -> None:
        score_raw = metrics.get(self.objective, 0.0)
        try:
            score = float(score_raw)
        except (TypeError, ValueError):
            return
        x = self._encode(params)
        self._obs_X.append(x)
        self._obs_y.append(score)
        self._gp.fit(self._obs_X, self._obs_y)
        if score > self._best_score:
            self._best_score = score
            self._best_params = dict(params)

    def suggest(
        self,
        stage: FlowStage,
        current_metrics: dict[str, Any],
        history: dict[str, Any],
    ) -> dict[str, Any]:
        self._call_count += 1
        if self._call_count <= self.n_initial:
            return self.space.sample(self._rng)

        best_ucb = -1e9
        best_params = self.space.sample(self._rng)
        for _ in range(50):
            candidate = self.space.sample(self._rng)
            x = self._encode(candidate)
            mu, sigma = self._gp.predict(x)
            ucb = mu + self.kappa * sigma
            if ucb > best_ucb:
                best_ucb = ucb
                best_params = candidate

        logger.info("[BAYES] stage=%s ucb=%.4f params=%s",
                    stage.value, best_ucb, best_params)
        return best_params

    def best(self) -> dict[str, Any]:
        return dict(self._best_params)
