"""Live samples stay fast enough for the dashboard timer."""

import time

import psutil

from traceos.collect import Collector, _linux_procs_running, _running


def test_linux_procs_running_reads_the_stat_field(tmp_path):
    path = tmp_path / "stat"
    path.write_text("cpu 1 2 3\nprocs_running 4\nprocs_blocked 1\n", encoding="ascii")
    assert _linux_procs_running(str(path)) == 4


def test_running_count_returns_quickly():
    timings = []
    values = []
    for _ in range(3):
        started = time.perf_counter()
        values.append(_running())
        timings.append(time.perf_counter() - started)
    assert all(isinstance(value, int) and value >= 0 for value in values)
    assert max(timings) < 0.5
    ceiling = max(64, (psutil.cpu_count(logical=True) or 1) * 8)
    assert max(values) <= ceiling


def test_one_live_sample_returns_quickly():
    collector = Collector()
    started = time.perf_counter()
    sample = collector.sample()
    assert time.perf_counter() - started < 0.5
    assert sample.proc_count >= 1
    assert sample.cpu_percent >= 0
    assert sample.running >= 0
