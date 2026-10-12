"""Command line for the observatory. With no arguments, the dashboard opens."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .collect import collect_seconds, host_meta
from .detect import detect_windows, ensure_model, holdout_accuracy, save_model, train_model
from .replay import run_experiment
from .report import render_report
from .samples import load_trace, save_trace
from .scenarios import demo_samples


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        from .dashboard import run

        return run()

    parser = argparse.ArgumentParser(prog="traceos", description="Trace OS MVP")
    parser.add_argument("--version", action="version", version=f"traceos {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("dashboard", help="open the PySide6 window")
    demo = sub.add_parser("demo", help="print a report for the built-in five-phase trace")
    demo.add_argument("--frames", type=int, default=3)
    demo.add_argument("--quantum", type=int, default=4)

    collect = sub.add_parser("collect", help="sample this machine and write a trace")
    collect.add_argument("--seconds", type=int, default=10)
    collect.add_argument("--out", default="data/live.json")

    sub.add_parser("train", help="fit the decision tree and save it")

    detect = sub.add_parser("detect", help="classify each window of a trace")
    detect.add_argument("trace")

    report = sub.add_parser("report", help="write a markdown report for a trace")
    report.add_argument("trace")
    report.add_argument("--out", default="data/report.md")
    report.add_argument("--frames", type=int, default=3)
    report.add_argument("--quantum", type=int, default=4)

    args = parser.parse_args(argv)
    if args.cmd == "dashboard":
        from .dashboard import run

        return run()
    if args.cmd == "demo":
        print(_report(demo_samples(), args.frames, args.quantum))
        return 0
    if args.cmd == "collect":
        samples = collect_seconds(args.seconds)
        save_trace(args.out, samples, host_meta())
        print(f"wrote {len(samples)} samples to {args.out}")
        return 0
    if args.cmd == "train":
        model = train_model()
        save_model(model)
        print(f"holdout accuracy {holdout_accuracy():.0%}")
        return 0
    if args.cmd == "detect":
        samples, _meta = load_trace(args.trace)
        for detection in detect_windows(samples, ensure_model()):
            print(f"{detection.start:3d}-{detection.end:<3d}  {detection.label}")
        return 0
    if args.cmd == "report":
        samples, _meta = load_trace(args.trace)
        text = _report(samples, args.frames, args.quantum)
        from pathlib import Path

        from .report import render_html

        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".html":
            text = render_html(text)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")
        return 0
    parser.error(args.cmd)
    return 2


def _report(samples, frames: int, quantum: int) -> str:
    return render_report(samples, detect_windows(samples, ensure_model()), run_experiment(samples, frames, quantum))


if __name__ == "__main__":
    raise SystemExit(main())
