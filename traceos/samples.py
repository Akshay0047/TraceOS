"""One observation of the machine, and the trace file that stores a series of them."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Sample:
    t: float
    cpu_percent: float
    mem_percent: float
    proc_count: int
    proc_born: int
    read_bytes: int
    write_bytes: int
    running: int
    page_faults: int = 0
    ctx_switches: int = 0


def save_trace(path: str | Path, samples: list[Sample], meta: dict | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "meta": meta or {}, "samples": [asdict(s) for s in samples]}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_trace(path: str | Path) -> tuple[list[Sample], dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    samples = [
        Sample(
            t=float(row["t"]),
            cpu_percent=float(row["cpu_percent"]),
            mem_percent=float(row["mem_percent"]),
            proc_count=int(row["proc_count"]),
            proc_born=int(row["proc_born"]),
            read_bytes=int(row["read_bytes"]),
            write_bytes=int(row["write_bytes"]),
            running=int(row["running"]),
            page_faults=int(row.get("page_faults", 0)),
            ctx_switches=int(row.get("ctx_switches", 0)),
        )
        for row in payload["samples"]
    ]
    return samples, payload.get("meta") or {}
