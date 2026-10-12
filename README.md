# Trace OS

Watch a machine, classify the workload, name the operating-system concept that explains it, and replay that same trace through scheduling and paging.

Observe → Detect → Explain → Experiment → Report.

## What this build does

**Observe.** Once a second, on Windows or on Linux, the collector records CPU, memory percent, process count, new processes, disk bytes, tasks currently executing, page faults, and context switches. The executing-task count is one system snapshot. It does not open a handle to every process. Samples are aggregated into windows of five. A single reading is never classified on its own.

**Detect.** A depth-limited decision tree, trained on synthetic windows with known labels, classifies each window as normal, CPU saturation, memory growth, a spawn storm, or heavy I/O. Confidence is the tree's probability for that leaf. An isolation forest, fit on the same synthetic windows, marks a window that does not look like those five classes.

**Explain.** The tree's splits are shown as a decision path and named as an OS concept: CPU scheduling, memory and paging, process creation, or blocking I/O.

**Experiment.** Each window becomes one job, and each sample contributes one page id. The same trace is run through FCFS, SJF, SRTF, priority, and round robin, and through FIFO, LRU, and optimal paging. The jobs and page ids are a teaching projection of the trace. They are not the kernel run queue and not the page tables.

**Report.** The desktop window shows the trace, the detections, the scheduler table, and the paging table. **Export report…** writes Markdown or HTML.

**Workload lab.** Short, contained stressors for a live sample: peg every logical CPU, climb resident memory, write a temporary file, start a few short-lived processes, or take two locks in opposite orders and give up before the process hangs.

## Not in this build

These were considered and left out:

- eBPF, and any in-kernel model
- a local language model
- Banker's algorithm
- cgroups
- Random Forest and XGBoost as the classifier. A single tree is used so the explanation can quote the splits.
- a full per-process tree of open files and threads. Walking every process froze the window.

Page faults and context switches are recorded and shown. They are not inputs to the tree. The tree splits on CPU, memory slope, spawn rate, and I/O, which is what keeps the five classes separable.

## Run

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m traceos
```

On Linux or WSL, use `.venv/bin/python -m traceos` after the same install.

`python -m traceos` with no arguments opens the window. `run_dashboard.bat` does the same on Windows.

If the terminal prints a Qt font note and no window appears, that terminal has `QT_QPA_PLATFORM=offscreen`. Clear it and start again:

```powershell
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
.venv\Scripts\python.exe -m traceos
```

In the window:

1. **Demo trace** is already applied at startup. The chart, the windows, the explanation, and the algorithm tables are on one screen. Click a window to shade it on the chart. **Samples** shows the raw table.
2. **Sample this PC (10s)** records a live trace and saves `data/live.json`.
3. The stress buttons run only while that sample is going, if you want the live trace to leave the normal class.
4. **Export…** writes Markdown or HTML.

From the terminal:

```powershell
.venv\Scripts\python.exe -m traceos demo
.venv\Scripts\python.exe -m traceos collect --seconds 10 --out data/live.json
.venv\Scripts\python.exe -m traceos report data/live.json --out data/report.md
.venv\Scripts\python.exe -m traceos report data/live.json --out data/report.html
.venv\Scripts\python.exe -m pytest -q
```

A two-minute speaking script for the existing-versus-proposed comparison and the implementation is in `docs/two-minute-script.pdf`.
