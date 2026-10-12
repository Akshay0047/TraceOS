"""Textbook CPU schedulers over integer time. Lower priority number runs first."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Job:
    jid: str
    arrival: int
    burst: int
    priority: int = 1


@dataclass(frozen=True, slots=True)
class JobResult:
    jid: str
    arrival: int
    burst: int
    priority: int
    start: int
    finish: int

    @property
    def turnaround(self) -> int:
        return self.finish - self.arrival

    @property
    def waiting(self) -> int:
        return self.turnaround - self.burst

    @property
    def response(self) -> int:
        return self.start - self.arrival


Slice = tuple[str, int, int]


@dataclass(frozen=True, slots=True)
class Schedule:
    key: str
    name: str
    slices: tuple[Slice, ...]
    jobs: tuple[JobResult, ...]

    @property
    def avg_waiting(self) -> float:
        return _avg(self.jobs, "waiting")

    @property
    def avg_turnaround(self) -> float:
        return _avg(self.jobs, "turnaround")

    @property
    def avg_response(self) -> float:
        return _avg(self.jobs, "response")


def _avg(jobs: tuple[JobResult, ...], attr: str) -> float:
    if not jobs:
        return 0.0
    return sum(getattr(job, attr) for job in jobs) / len(jobs)


def _validate(jobs: list[Job]) -> None:
    ids = [job.jid for job in jobs]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate job id")
    for job in jobs:
        if job.burst < 1:
            raise ValueError(f"{job.jid}: burst must be >= 1")
        if job.arrival < 0:
            raise ValueError(f"{job.jid}: arrival must be >= 0")


def _add(slices: list[Slice], jid: str, start: int, end: int) -> None:
    if end <= start:
        return
    if slices and slices[-1][0] == jid and slices[-1][2] == start:
        prev = slices[-1]
        slices[-1] = (prev[0], prev[1], end)
    else:
        slices.append((jid, start, end))


def _order(jobs: list[Job], done: list[JobResult]) -> tuple[JobResult, ...]:
    rank = {job.jid: i for i, job in enumerate(jobs)}
    done.sort(key=lambda result: rank[result.jid])
    return tuple(done)


def _nonpreemptive(jobs: list[Job], key) -> tuple[list[Slice], tuple[JobResult, ...]]:
    pending = sorted(jobs, key=lambda job: (job.arrival, job.jid))
    ready: list[Job] = []
    index = 0
    t = 0
    slices: list[Slice] = []
    done: list[JobResult] = []
    while index < len(pending) or ready:
        if not ready:
            nxt = pending[index].arrival
            if t < nxt:
                _add(slices, "idle", t, nxt)
                t = nxt
        while index < len(pending) and pending[index].arrival <= t:
            ready.append(pending[index])
            index += 1
        if not ready:
            break
        ready.sort(key=key)
        job = ready.pop(0)
        start = t
        t += job.burst
        _add(slices, job.jid, start, t)
        done.append(JobResult(job.jid, job.arrival, job.burst, job.priority, start, t))
    return slices, _order(jobs, done)


def _preemptive(jobs: list[Job], mode: str, quantum: int) -> tuple[list[Slice], tuple[JobResult, ...]]:
    if mode == "rr" and quantum < 1:
        raise ValueError("quantum must be >= 1")
    pending = sorted(jobs, key=lambda job: (job.arrival, job.jid))
    remaining = {job.jid: job.burst for job in jobs}
    meta = {job.jid: job for job in jobs}
    ready: list[str] = []
    index = 0
    t = 0
    slices: list[Slice] = []
    current: str | None = None
    used = 0
    first: dict[str, int] = {}
    finish: dict[str, int] = {}
    limit = max((job.arrival for job in jobs), default=0) + sum(job.burst for job in jobs) + 2
    while len(finish) < len(jobs):
        if t > limit:
            raise RuntimeError("scheduler did not finish")
        while index < len(pending) and pending[index].arrival <= t:
            ready.append(pending[index].jid)
            index += 1
        if mode == "srtf" and current is not None:
            ready.append(current)
            current = None
        if current is None:
            if not ready:
                if index >= len(pending):
                    break
                nxt = pending[index].arrival
                _add(slices, "idle", t, nxt)
                t = nxt
                continue
            if mode == "srtf":
                ready.sort(key=lambda jid: (remaining[jid], meta[jid].arrival, jid))
            current = ready.pop(0)
            used = 0
            first.setdefault(current, t)
        _add(slices, current, t, t + 1)
        remaining[current] -= 1
        used += 1
        t += 1
        if remaining[current] == 0:
            finish[current] = t
            current = None
        elif mode == "rr" and used >= quantum:
            ready.append(current)
            current = None
    done = [
        JobResult(job.jid, job.arrival, job.burst, job.priority, first[job.jid], finish[job.jid])
        for job in jobs
    ]
    return slices, tuple(done)


def schedule(jobs: list[Job], key: str, quantum: int = 4) -> Schedule:
    _validate(jobs)
    if key == "fcfs":
        slices, results = _nonpreemptive(jobs, lambda job: (job.arrival, job.jid))
        name = "FCFS"
    elif key == "sjf":
        slices, results = _nonpreemptive(jobs, lambda job: (job.burst, job.arrival, job.jid))
        name = "SJF"
    elif key == "priority":
        slices, results = _nonpreemptive(jobs, lambda job: (job.priority, job.arrival, job.jid))
        name = "Priority"
    elif key == "srtf":
        slices, results = _preemptive(jobs, "srtf", quantum)
        name = "SRTF"
    elif key == "rr":
        slices, results = _preemptive(jobs, "rr", quantum)
        name = f"RR q={quantum}"
    else:
        raise ValueError(key)
    for result in results:
        if result.start < result.arrival or result.finish < result.arrival + result.burst:
            raise RuntimeError(f"illegal timeline for {result.jid}")
    return Schedule(key, name, tuple(slices), results)


def compare_all(jobs: list[Job], quantum: int = 4) -> list[Schedule]:
    return [schedule(jobs, key, quantum) for key in ("fcfs", "sjf", "srtf", "priority", "rr")]


def format_gantt(schedule_result: Schedule) -> str:
    return "  ".join(f"{jid} [{start}-{end}]" for jid, start, end in schedule_result.slices)
