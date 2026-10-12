"""Labeled windows used to train the tree, and the offline demo trace.

The five classes are separated on purpose. The tree then learns a threshold a person
can read (CPU near saturation, resident-set slope, births per second, megabytes per
second). It is not a detector trained on a production incident log.
"""

from __future__ import annotations

import numpy as np

from .features import LABELS
from .samples import Sample

# Non-saturation classes share a CPU band so the tree cannot use CPU as a proxy
# for memory growth, spawn storms, or heavy I/O.
_CPU = {
    "normal": 35.0,
    "cpu_saturation": 94.0,
    "memory_growth": 35.0,
    "spawn_storm": 35.0,
    "io_heavy": 35.0,
}


def make_window(label: str, n: int = 5, rng: np.random.Generator | None = None, t0: float = 0.0) -> list[Sample]:
    if label not in _CPU:
        raise ValueError(label)
    slope = 2.0 if label == "memory_growth" else 0.0
    born = 3 if label == "spawn_storm" else 0
    write = 20_000_000 if label == "io_heavy" else 40_000
    cpu = _CPU[label]
    running = 3
    if rng is not None:
        slope += float(rng.uniform(-0.25, 0.25) if label == "memory_growth" else rng.uniform(-0.15, 0.15))
        cpu = min(100.0, max(0.0, cpu + float(rng.uniform(-12.0, 12.0))))
        if label == "spawn_storm":
            born = int(rng.integers(2, 5))
        write = int(write * float(rng.uniform(0.75, 1.25)))
        running = max(0, running + int(rng.integers(-1, 2)))
    samples = []
    for i in range(n):
        samples.append(
            Sample(
                t=t0 + i,
                cpu_percent=cpu,
                mem_percent=min(100.0, max(0.0, 40.0 + i * slope)),
                proc_count=120 + born,
                proc_born=born,
                read_bytes=0,
                write_bytes=write,
                running=running,
            )
        )
    return samples


def demo_samples() -> list[Sample]:
    """Five clean phases, in label order: normal, CPU, memory, spawn, I/O."""
    samples: list[Sample] = []
    t0 = 0.0
    for label in LABELS:
        phase = make_window(label, t0=t0)
        samples.extend(phase)
        t0 += len(phase)
    return samples


def synthesize(n_per_class: int = 60, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    from .features import vector, window_features

    rng = np.random.default_rng(seed)
    rows: list[list[float]] = []
    labels: list[str] = []
    for label in LABELS:
        for _ in range(n_per_class):
            rows.append(vector(window_features(make_window(label, rng=rng))))
            labels.append(label)
    return np.asarray(rows, dtype=float), np.asarray(labels)
