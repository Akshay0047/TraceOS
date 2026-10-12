"""The workload lab stays short and returns the machine to the caller."""

import time

from traceos.workloads import burst_io, contained_lock_order, grow_memory, spawn_burst


def test_stressors_finish():
    started = time.perf_counter()
    grow_memory(0.05, megabytes=16)
    burst_io(0.15)
    spawn_burst(0.3)
    text = contained_lock_order(0.2)
    assert time.perf_counter() - started < 8
    assert "lock" in text
