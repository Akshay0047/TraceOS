"""Project a trace onto scheduler jobs and a page-reference string.

The projection is a teaching input. It is not the kernel run queue and it is not the
process page table. CPU level becomes the burst, window order becomes the arrival,
and each sample contributes one page id from the signals in that sample.
"""

from __future__ import annotations

from dataclasses import dataclass

from .features import iter_windows, window_features
from .paging import PageResult, compare_paging
from .samples import Sample
from .schedulers import Job, Schedule, compare_all


@dataclass(frozen=True, slots=True)
class Experiment:
    jobs: tuple[Job, ...]
    refs: tuple[int, ...]
    frames: int
    quantum: int
    schedules: tuple[Schedule, ...]
    paging: tuple[PageResult, ...]


def derive_jobs(samples: list[Sample]) -> list[Job]:
    jobs: list[Job] = []
    for index, (start, window) in enumerate(iter_windows(samples)):
        feats = window_features(window)
        burst = max(1, min(30, round(feats["cpu_mean"] / 5)))
        if feats["spawn_per_s"] >= 1.5:
            priority = 1
        elif feats["io_mb_s"] >= 5:
            priority = 2
        elif feats["cpu_mean"] >= 80:
            priority = 4
        else:
            priority = 3
        jobs.append(Job(f"w{index}", start, burst, priority))
    return jobs


def derive_refs(samples: list[Sample]) -> list[int]:
    refs = []
    for index, sample in enumerate(samples):
        page = int(sample.cpu_percent) // 25
        if sample.proc_born >= 2:
            page += 1
        if sample.write_bytes >= 1_000_000:
            page += 2
        page = (page + (index % 3)) % 6
        refs.append(page)
    return refs


def run_experiment(samples: list[Sample], frames: int = 3, quantum: int = 4) -> Experiment:
    jobs = derive_jobs(samples)
    refs = derive_refs(samples)
    schedules = tuple(compare_all(jobs, quantum)) if jobs else ()
    paging = tuple(compare_paging(refs, frames)) if refs else ()
    return Experiment(tuple(jobs), tuple(refs), frames, quantum, schedules, paging)
