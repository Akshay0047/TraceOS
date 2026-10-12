"""Sample CPU, memory, process births, and disk bytes. Works on Windows and on Linux."""

from __future__ import annotations

import platform
import time

import psutil

from .samples import Sample


class Collector:
    def __init__(self) -> None:
        psutil.cpu_percent(interval=None)
        self._pids = set(psutil.pids())
        self._io = psutil.disk_io_counters()
        self._t0 = time.perf_counter()

    def sample(self) -> Sample:
        cpu = float(psutil.cpu_percent(interval=None))
        mem = float(psutil.virtual_memory().percent)
        pids = set(psutil.pids())
        born = len(pids - self._pids)
        self._pids = pids
        io = psutil.disk_io_counters()
        read = write = 0
        if io is not None and self._io is not None:
            read = max(0, int(io.read_bytes - self._io.read_bytes))
            write = max(0, int(io.write_bytes - self._io.write_bytes))
        self._io = io
        return Sample(
            t=time.perf_counter() - self._t0,
            cpu_percent=cpu,
            mem_percent=mem,
            proc_count=len(pids),
            proc_born=born,
            read_bytes=read,
            write_bytes=write,
            running=_running(),
        )


def host_meta() -> dict:
    return {
        "platform": platform.platform(),
        "cpu_count": psutil.cpu_count(logical=True) or 1,
        "memory_gb": round(psutil.virtual_memory().total / 2**30, 2),
    }


def collect_seconds(seconds: int, interval: float = 1.0) -> list[Sample]:
    if seconds < 1:
        raise ValueError("seconds must be >= 1")
    collector = Collector()
    samples: list[Sample] = []
    for _ in range(seconds):
        time.sleep(interval)
        samples.append(collector.sample())
    return samples


def _running() -> int:
    count = 0
    for proc in psutil.process_iter(["status"]):
        try:
            if proc.info["status"] == psutil.STATUS_RUNNING:
                count += 1
        except (psutil.Error, KeyError):
            continue
    return count
