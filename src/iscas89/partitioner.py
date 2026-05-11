from __future__ import annotations
import random
from dataclasses import dataclass, field
from typing import Any

from .bench_parser import Circuit


@dataclass
class PartitionResult:
    circuit_name: str
    k: int                             # number of partitions
    assignment: dict[str, int]         # gate_name -> partition id
    cut_nets: int                       # number of nets crossing partitions
    total_nets: int
    cut_ratio: float
    balance: float                     # 0..1, 1=perfectly balanced
    partition_sizes: list[int]
    iterations: int


class FMPartitioner:
    """
    Fiduccia-Mattheyses 2-way partitioner.
    Classic O(|pins|) passes, returns best cut found.
    For k>2: recursive bisection.
    """

    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)

    def partition(self, circ: Circuit, k: int = 2) -> PartitionResult:
        cells = list(circ.gates.keys())
        if not cells:
            return PartitionResult(circ.name, k, {}, 0, 0, 0.0, 1.0, [0]*k, 0)

        if k == 2:
            assignment, cut_nets, iters = self._fm_2way(circ, cells)
        else:
            assignment, cut_nets, iters = self._recursive_bisect(circ, cells, k)

        sizes = [0] * k
        for p in assignment.values():
            sizes[p] += 1
        n = len(cells)
        balance = 1.0 - abs(sizes[0] - sizes[1]) / n if k == 2 else \
                  1.0 - (max(sizes) - min(sizes)) / n

        total_nets = len(circ.gates)
        cut_ratio = cut_nets / total_nets if total_nets > 0 else 0.0

        # Assign to Gate objects
        for gname, pid in assignment.items():
            if gname in circ.gates:
                circ.gates[gname].partition = pid

        return PartitionResult(
            circuit_name=circ.name,
            k=k,
            assignment=assignment,
            cut_nets=cut_nets,
            total_nets=total_nets,
            cut_ratio=cut_ratio,
            balance=balance,
            partition_sizes=sizes,
            iterations=iters,
        )

    def _initial_assignment(self, cells: list[str]) -> dict[str, int]:
        assign = {}
        half = len(cells) // 2
        shuffled = cells[:]
        self.rng.shuffle(shuffled)
        for i, c in enumerate(shuffled):
            assign[c] = 0 if i < half else 1
        return assign

    def _fm_2way(
        self, circ: Circuit, cells: list[str]
    ) -> tuple[dict[str, int], int, int]:
        assign = self._initial_assignment(cells)
        best_assign = dict(assign)
        best_cut = self._count_cut(circ, assign)
        total_iters = 0

        for _pass in range(20):
            gain_map = self._compute_gains(circ, assign, cells)
            locked: set[str] = set()
            seq_gains: list[tuple[int, str, dict]] = []
            current_assign = dict(assign)

            for _ in range(len(cells)):
                candidates = [
                    (g, c) for c, g in gain_map.items()
                    if c not in locked and self._move_preserves_balance(
                        c, current_assign, len(cells)
                    )
                ]
                if not candidates:
                    break
                candidates.sort(key=lambda x: x[0], reverse=True)
                best_gain, best_cell = candidates[0]
                # Move best_cell
                old_p = current_assign[best_cell]
                current_assign[best_cell] = 1 - old_p
                locked.add(best_cell)
                seq_gains.append((best_gain, best_cell, dict(current_assign)))
                # Update gains for unlocked neighbours
                for nb in self._neighbors(circ, best_cell):
                    if nb not in locked and nb in gain_map:
                        gain_map[nb] += (2 if current_assign.get(nb, 0)
                                          == current_assign.get(best_cell, 0)
                                          else -2)

            # Find prefix of sequence with best cumulative gain
            cum = 0
            best_cum = 0
            best_idx = -1
            for idx, (g, _, _) in enumerate(seq_gains):
                cum += g
                if cum > best_cum:
                    best_cum = cum
                    best_idx = idx

            if best_idx >= 0:
                assign = seq_gains[best_idx][2]
                cut = self._count_cut(circ, assign)
                if cut < best_cut:
                    best_cut = cut
                    best_assign = dict(assign)

            total_iters += 1
            if best_cum <= 0:
                break

        return best_assign, best_cut, total_iters

    def _compute_gains(
        self, circ: Circuit, assign: dict[str, int], cells: list[str]
    ) -> dict[str, int]:
        gains: dict[str, int] = {}
        for cell in cells:
            gains[cell] = self._cell_gain(circ, assign, cell)
        return gains

    def _cell_gain(self, circ: Circuit, assign: dict[str, int], cell: str) -> int:
        my_part = assign.get(cell, 0)
        other_part = 1 - my_part
        gain = 0
        for inp in circ.gates[cell].inputs:
            nb_part = assign.get(inp, 0)
            if nb_part == my_part:
                gain -= 1
            else:
                gain += 1
        for sink in circ.fanout.get(cell, []):
            if sink in assign:
                nb_part = assign[sink]
                if nb_part == my_part:
                    gain -= 1
                else:
                    gain += 1
        return gain

    def _neighbors(self, circ: Circuit, cell: str) -> list[str]:
        nbs = list(circ.gates[cell].inputs)
        nbs.extend(circ.fanout.get(cell, []))
        return [n for n in nbs if n in circ.gates]

    def _count_cut(self, circ: Circuit, assign: dict[str, int]) -> int:
        cut = 0
        for name, gate in circ.gates.items():
            my_p = assign.get(name, 0)
            for inp in gate.inputs:
                if assign.get(inp, 0) != my_p:
                    cut += 1
                    break
        return cut

    def _move_preserves_balance(
        self, cell: str, assign: dict[str, int], n: int
    ) -> bool:
        p = assign.get(cell, 0)
        cnt_p = sum(1 for v in assign.values() if v == p)
        return cnt_p > n // 4

    def _recursive_bisect(
        self, circ: Circuit, cells: list[str], k: int
    ) -> tuple[dict[str, int], int, int]:
        if k == 1:
            return {c: 0 for c in cells}, 0, 0
        half_k1 = k // 2
        half_k2 = k - half_k1
        assign, cut, iters = self._fm_2way(circ, cells)
        left = [c for c, p in assign.items() if p == 0]
        right = [c for c, p in assign.items() if p == 1]

        sub_l, _, it_l = self._recursive_bisect(circ, left, half_k1)
        sub_r, _, it_r = self._recursive_bisect(circ, right, half_k2)

        final: dict[str, int] = {}
        for c, p in sub_l.items():
            final[c] = p
        for c, p in sub_r.items():
            final[c] = p + half_k1

        total_cut = self._count_cut_k(circ, final)
        return final, total_cut, iters + it_l + it_r

    def _count_cut_k(self, circ: Circuit, assign: dict[str, int]) -> int:
        cut = 0
        for name, gate in circ.gates.items():
            my_p = assign.get(name, 0)
            for inp in gate.inputs:
                if assign.get(inp, my_p) != my_p:
                    cut += 1
                    break
        return cut
