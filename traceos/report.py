"""Markdown report covering detection, the derived jobs, and both algorithm tables."""

from __future__ import annotations

from .detect import Detection
from .explain import CONCEPTS
from .replay import Experiment
from .samples import Sample
from .schedulers import format_gantt


def render_report(samples: list[Sample], detections: list[Detection], experiment: Experiment) -> str:
    lines: list[str] = ["# Trace OS report", ""]
    if samples:
        lines.append(f"Samples: {len(samples)}. Time {samples[0].t:g} to {samples[-1].t:g}.")
    else:
        lines.append("Samples: 0.")
    lines.append("")
    lines.append("## Detections")
    lines.append("")
    if not detections:
        lines.append("No window was long enough to classify.")
    else:
        lines.append("| Window | Label | OS concept | Decision path |")
        lines.append("|---|---|---|---|")
        for detection in detections:
            title = CONCEPTS.get(detection.label, ("",))[0]
            path = " ; ".join(detection.rules)
            lines.append(
                f"| {detection.start}-{detection.end} | {detection.label} | {title} | {path} |"
            )
    lines.extend(["", "## Derived jobs", ""])
    lines.append(
        "Each window is one job. Arrival is the first sample index of that window. "
        "Burst is round(mean CPU / 5). Priority 1 is a spawn storm, 2 is heavy I/O, "
        "3 is ordinary, and 4 is CPU saturation. A lower number runs first."
    )
    lines.append("")
    if not experiment.jobs:
        lines.append("No jobs.")
    else:
        lines.append("| Job | Arrival | Burst | Priority |")
        lines.append("|---|---:|---:|---:|")
        for job in experiment.jobs:
            lines.append(f"| {job.jid} | {job.arrival} | {job.burst} | {job.priority} |")
    lines.extend(["", "## Scheduling", ""])
    if experiment.schedules:
        best_wait = min(item.avg_waiting for item in experiment.schedules)
        best_names = [item.name for item in experiment.schedules if item.avg_waiting == best_wait]
        lines.append(f"Lowest average waiting: **{', '.join(best_names)}** ({best_wait:.2f}).")
        lines.append("")
        lines.append("| Algorithm | Avg waiting | Avg turnaround | Avg response |")
        lines.append("|---|---:|---:|---:|")
        for item in experiment.schedules:
            lines.append(
                f"| {item.name} | {item.avg_waiting:.2f} | {item.avg_turnaround:.2f} | {item.avg_response:.2f} |"
            )
        lines.append("")
        for item in experiment.schedules:
            lines.append(f"### {item.name}")
            lines.append("")
            lines.append(format_gantt(item))
            lines.append("")
            lines.append("| Job | Start | Finish | Waiting | Turnaround |")
            lines.append("|---|---:|---:|---:|---:|")
            for job in item.jobs:
                lines.append(
                    f"| {job.jid} | {job.start} | {job.finish} | {job.waiting} | {job.turnaround} |"
                )
            lines.append("")
    lines.extend(["## Paging", ""])
    if experiment.refs:
        shown = " ".join(str(page) for page in experiment.refs)
        lines.append(f"Frames: {experiment.frames}. Reference string: `{shown}`.")
        lines.append("")
        lines.append(
            "One page id per sample, from the CPU band, whether the sample created processes, "
            "whether it wrote at least a megabyte, and the sample index. "
            "Optimal is the lower bound on faults for this string."
        )
        lines.append("")
        lines.append("| Algorithm | Faults | Fault rate |")
        lines.append("|---|---:|---:|")
        for item in experiment.paging:
            lines.append(f"| {item.name} | {item.faults} | {item.fault_rate:.0%} |")
        fewest_n = min(item.faults for item in experiment.paging)
        fewest_names = [item.name for item in experiment.paging if item.faults == fewest_n]
        lines.append("")
        lines.append(f"Fewest faults: **{', '.join(fewest_names)}** ({fewest_n}).")
    lines.extend(
        [
            "",
            "## What the model is",
            "",
            "The classifier is a depth-limited decision tree. It was trained on synthetic windows "
            "whose labels are the five workload classes, with a little noise. Live samples from this "
            "PC are classified by that tree. The decision path above is the explanation: the splits "
            "the tree actually used, named as CPU scheduling, paging, process creation, or I/O.",
            "",
        ]
    )
    return "\n".join(lines)
