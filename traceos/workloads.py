"""Short, obvious stressors for the live demo. They are not the training set."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

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


def grow_memory(seconds: float = 3.0, megabytes: int | None = None) -> None:
    """Grow the resident set in steps, then release it.

    One lump allocation jumps once and then sits flat, so a window never sees a slope.
    Several steps across the interval are what the memory-growth class is looking for.
    """
    if megabytes is None:
        total_mb = psutil.virtual_memory().total / (1024 * 1024)
        megabytes = int(min(1024, max(160, total_mb * 0.06)))
    steps = 6
    chunk = max(1, megabytes) * 1024 * 1024 // steps
    pause = max(0.0, seconds) / steps
    blocks: list[bytearray] = []
    for _ in range(steps):
        block = bytearray(chunk)
        for index in range(0, len(block), 4096):
            block[index] = 1
        blocks.append(block)
        time.sleep(pause)
    del blocks


def burst_io(seconds: float = 3.0) -> None:
    """Write and flush a temporary file so the disk counters move."""
    path = Path(tempfile.gettempdir()) / "traceos-io.bin"
    chunk = b"x" * (1 << 20)
    end = time.perf_counter() + max(0.05, seconds)
    try:
        with path.open("wb") as handle:
            while time.perf_counter() < end:
                handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
    finally:
        path.unlink(missing_ok=True)


def spawn_burst(seconds: float = 3.0) -> None:
    """Start a few short-lived processes. This is not a fork bomb."""
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    end = time.perf_counter() + max(0.05, seconds)
    children: list[subprocess.Popen] = []
    while time.perf_counter() < end and len(children) < 12:
        children.append(
            subprocess.Popen(
                [sys.executable, "-c", "pass"],
                creationflags=flags,
            )
        )
        time.sleep(0.25)
    for child in children:
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()


def contained_lock_order(timeout: float = 0.4) -> str:
    """Two threads take locks in opposite orders and give up instead of hanging."""
    first = threading.Lock()
    second = threading.Lock()
    outcome: list[str] = []

    def take(name: str, left: threading.Lock, right: threading.Lock, pause: float) -> None:
        if not left.acquire(timeout=timeout):
            outcome.append(f"{name} did not get the first lock")
            return
        try:
            time.sleep(pause)
            if right.acquire(timeout=timeout):
                right.release()
                outcome.append(f"{name} got both locks")
            else:
                outcome.append(f"{name} blocked on the second lock")
        finally:
            left.release()

    workers = [
        threading.Thread(target=take, args=("A", first, second, timeout), daemon=True),
        threading.Thread(target=take, args=("B", second, first, timeout / 2), daemon=True),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=timeout * 4 + 0.5)
    return "; ".join(outcome) if outcome else "no result"
