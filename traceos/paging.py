"""FIFO, LRU, and optimal page replacement over a reference string."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PageResult:
    name: str
    frames: int
    references: int
    faults: int

    @property
    def fault_rate(self) -> float:
        if self.references == 0:
            return 0.0
        return self.faults / self.references


def fifo(refs: list[int], frames: int) -> int:
    return _count(refs, frames, "fifo")


def lru(refs: list[int], frames: int) -> int:
    return _count(refs, frames, "lru")


def optimal(refs: list[int], frames: int) -> int:
    return _count(refs, frames, "optimal")


def compare_paging(refs: list[int], frames: int) -> list[PageResult]:
    if frames < 1:
        raise ValueError("frames must be >= 1")
    return [
        PageResult("FIFO", frames, len(refs), fifo(refs, frames)),
        PageResult("LRU", frames, len(refs), lru(refs, frames)),
        PageResult("Optimal", frames, len(refs), optimal(refs, frames)),
    ]


def _count(refs: list[int], frames: int, policy: str) -> int:
    if frames < 1:
        raise ValueError("frames must be >= 1")
    memory: list[int] = []
    faults = 0
    for index, page in enumerate(refs):
        if page in memory:
            if policy == "lru":
                memory.remove(page)
                memory.append(page)
            continue
        faults += 1
        if len(memory) < frames:
            memory.append(page)
            continue
        if policy == "optimal":
            memory[_farthest(memory, refs, index)] = page
        else:
            # Index 0 is the oldest resident (FIFO order, or least recently used).
            memory.pop(0)
            memory.append(page)
    return faults


def _farthest(memory: list[int], refs: list[int], index: int) -> int:
    def next_use(page: int) -> int:
        for later in range(index + 1, len(refs)):
            if refs[later] == page:
                return later
        return len(refs) + memory.index(page)

    return max(range(len(memory)), key=lambda slot: next_use(memory[slot]))
