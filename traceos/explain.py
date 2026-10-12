"""Map a predicted class and the tree's own splits onto an OS concept."""

from __future__ import annotations

from .detect import Detection

CONCEPTS = {
    "normal": (
        "Steady state",
        "CPU, memory, process creation, and I/O all sit in an ordinary band. "
        "The ready queue is not backed up, and the resident set is not forcing the pager to reclaim frames.",
    ),
    "cpu_saturation": (
        "CPU scheduling",
        "The processor stayed near saturation, so the ready queue was rarely empty. "
        "A CPU-bound run lengthens waiting time for everyone else. This is the situation "
        "FCFS, SJF, SRTF, and round robin are compared on.",
    ),
    "memory_growth": (
        "Memory and paging",
        "The resident set grew across the window. If that continues, free frames fall and the "
        "pager starts evicting. FIFO, LRU, and the optimal policy then disagree about which page to give up.",
    ),
    "spawn_storm": (
        "Process creation",
        "New processes appeared several times a second. Each creation allocates a process control block "
        "and an address space and places a thread on the ready queue, so the CPU spends time on bookkeeping.",
    ),
    "io_heavy": (
        "I/O and blocking",
        "The window moved megabytes while the CPU stayed comparatively idle. Those tasks are I/O-bound: "
        "they block on a wait queue, the scheduler switches away, and the disk becomes the bottleneck.",
    ),
}


def explain(detection: Detection) -> str:
    title, summary = CONCEPTS.get(detection.label, ("Unclassified", "No concept is mapped to this label."))
    features = "\n".join(f"  {name:<14} {value:.3g}" for name, value in detection.features.items())
    rules = "\n".join(f"  {rule}" for rule in detection.rules) or "  (leaf reached with no split)"
    return (
        f"{detection.label}   samples {detection.start}-{detection.end}\n"
        f"{title}\n\n"
        f"{summary}\n\n"
        f"Window features\n{features}\n\n"
        f"Decision path\n{rules}"
    )
