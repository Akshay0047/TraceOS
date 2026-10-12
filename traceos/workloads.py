"""Short, obvious stressors for the live demo. They are not the training set."""

from __future__ import annotations

import threading
import time

import psutil


def burn_cpu(seconds: float = 3.0) -> None:
    """Keep every logical CPU busy so a live sample can cross the saturation split."""
    cores = max(1, psutil.cpu_count(logical=True) or 1)
    end = time.perf_counter() + seconds

    def spin() -> None:
        while time.perf_counter() < end:
            pass

    workers = [threading.Thread(target=spin, daemon=True) for _ in range(cores)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
