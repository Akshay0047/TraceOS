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
        lines.append("| Window | Label | Confidence | OS concept | Decision path |")
        lines.append("|---|---|---:|---|---|")
        for detection in detections:
            title = CONCEPTS.get(detection.label, ("",))[0]
            path = " ; ".join(detection.rules)
            mark = " unseen" if detection.outlier else ""
            lines.append(
                f"| {detection.start}-{detection.end} | {detection.label}{mark} | "
                f"{detection.confidence:.0%} | {title} | {path} |"
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
            "Known patterns are classified by a depth-limited decision tree trained on synthetic "
            "windows of the five workload classes, with a little noise. Confidence is the tree's "
            "probability for the chosen leaf. An isolation forest, fit on the same synthetic windows, "
            "marks a window that does not look like those classes. The decision path is the explanation: "
            "the splits the tree actually used, named as CPU scheduling, paging, process creation, or I/O. "
            "Page faults and context switches are recorded with each sample and are not inputs to the tree.",
            "",
        ]
    )
    return "\n".join(lines)


def render_html(markdown: str) -> str:
    """A single HTML page for the same report. Tables stay tables."""
    import html as html_lib

    parts = [
        "<!DOCTYPE html>",
        "<html><head><meta charset=\"utf-8\">",
        "<title>Trace OS report</title>",
        "<style>",
        "body{font-family:Segoe UI,sans-serif;max-width:920px;margin:2rem auto;color:#1c2833;}",
        "table{border-collapse:collapse;width:100%;margin:0.5rem 0 1.2rem;}",
        "th,td{border:1px solid #d5dee8;padding:4px 8px;text-align:left;vertical-align:top;}",
        "th{background:#e7eef5;}",
        "code{background:#f4f7fa;padding:0 4px;}",
        "</style></head><body>",
    ]
    rows: list[str] = []

    def flush_table() -> None:
        if not rows:
            return
        parts.append("<table>")
        for index, row in enumerate(rows):
            cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
            tag = "th" if index == 0 else "td"
            parts.append("<tr>" + "".join(f"<{tag}>{html_lib.escape(cell)}</{tag}>" for cell in cells) + "</tr>")
        parts.append("</table>")
        rows.clear()

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if line.startswith("|"):
            if set(line.replace("|", "").replace("-", "").replace(":", "").strip()) == set():
                continue
            rows.append(line)
            continue
        flush_table()
        if not line:
            continue
        if line.startswith("### "):
            parts.append(f"<h3>{html_lib.escape(line[4:])}</h3>")
        elif line.startswith("## "):
            parts.append(f"<h2>{html_lib.escape(line[3:])}</h2>")
        elif line.startswith("# "):
            parts.append(f"<h1>{html_lib.escape(line[2:])}</h1>")
        else:
            text = html_lib.escape(line).replace("**", "")
            text = text.replace("`", "")
            parts.append(f"<p>{text}</p>")
    flush_table()
    parts.append("</body></html>")
    return "\n".join(parts)
