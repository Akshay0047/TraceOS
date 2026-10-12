"""Sliding-window features. Training and live detection both call this function."""

from __future__ import annotations

from .samples import Sample

FEATURE_NAMES = (
    "cpu_mean",
    "cpu_max",
    "mem_slope",
    "spawn_per_s",
    "io_mb_s",
    "running_mean",
)

LABELS = ("normal", "cpu_saturation", "memory_growth", "spawn_storm", "io_heavy")

WINDOW = 5
STEP = 5


def window_features(samples: list[Sample]) -> dict[str, float]:
    if not samples:
        raise ValueError("empty window")
    n = len(samples)
    if n == 1:
        span = 1.0
        duration = 1.0
    else:
        span = samples[-1].t - samples[0].t
        if span <= 0:
            span = float(n - 1)
        # Each sample closes one interval, so n samples cover n intervals.
        duration = span * n / (n - 1)
    cpus = [s.cpu_percent for s in samples]
    io_bytes = sum(s.read_bytes + s.write_bytes for s in samples)
    return {
        "cpu_mean": sum(cpus) / n,
        "cpu_max": max(cpus),
        "mem_slope": (samples[-1].mem_percent - samples[0].mem_percent) / span,
        "spawn_per_s": sum(s.proc_born for s in samples) / duration,
        "io_mb_s": io_bytes / duration / 1e6,
        "running_mean": sum(s.running for s in samples) / n,
    }


def vector(features: dict[str, float]) -> list[float]:
    return [float(features[name]) for name in FEATURE_NAMES]


def iter_windows(samples: list[Sample], size: int = WINDOW, step: int = STEP):
    """Yield (start_index, window). A short trace is one window so a brief sample still classifies."""
    if not samples:
        return
    if len(samples) < size:
        yield 0, list(samples)
        return
    start = 0
    while start + size <= len(samples):
        yield start, samples[start : start + size]
        start += step
