"""Scheduler timelines checked against hand-worked examples."""

import pytest

from traceos.schedulers import Job, schedule


def _jobs():
    return [
        Job("P1", 0, 7, 1),
        Job("P2", 2, 4, 1),
        Job("P3", 4, 1, 1),
        Job("P4", 5, 4, 1),
    ]


def _waiting(key, jobs=None, quantum=4):
    result = schedule(jobs if jobs is not None else _jobs(), key, quantum)
    return {job.jid: job.waiting for job in result.jobs}


def test_fcfs_waiting():
    assert _waiting("fcfs") == {"P1": 0, "P2": 5, "P3": 7, "P4": 7}
    assert schedule(_jobs(), "fcfs").avg_waiting == pytest.approx(4.75)


def test_sjf_waiting():
    assert _waiting("sjf") == {"P1": 0, "P2": 6, "P3": 3, "P4": 7}


def test_srtf_waiting():
    assert _waiting("srtf") == {"P1": 9, "P2": 1, "P3": 0, "P4": 2}
    assert schedule(_jobs(), "srtf").avg_waiting == pytest.approx(3)


def test_priority_prefers_lower_number():
    jobs = [Job("A", 0, 4, 2), Job("B", 0, 2, 1), Job("C", 1, 1, 3)]
    assert _waiting("priority", jobs) == {"A": 2, "B": 0, "C": 5}


def test_round_robin_quantum_two():
    jobs = [Job("A", 0, 4, 1), Job("B", 0, 3, 1)]
    assert _waiting("rr", jobs, quantum=2) == {"A": 2, "B": 4}


def test_gantt_marks_idle_gap():
    result = schedule([Job("A", 0, 1, 1), Job("B", 4, 1, 1)], "fcfs")
    assert ("idle", 1, 4) in result.slices
