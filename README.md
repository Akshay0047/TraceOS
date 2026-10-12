# Trace OS

An MVP of the operating-systems project: watch a machine, classify the workload, say which OS concept explains it, and replay that same trace through scheduling and paging.

Observe → Detect → Explain → Experiment → Report.

## What the MVP does

- Samples CPU, memory, process count, new processes, disk bytes, and running processes once a second (`psutil`, so it runs on Windows and on Linux / WSL).
- Classifies each 5-sample window as normal, CPU saturation, memory growth, a spawn storm, or heavy I/O.
- Shows the decision-tree path and the OS concept that goes with the class: scheduling, paging, process creation, or blocking I/O.
- Turns the trace into jobs and a page-reference string, then runs FCFS, SJF, SRTF, Priority, and Round Robin, plus FIFO, LRU, and Optimal.

The tree is trained on synthetic windows with known labels, so the splits stay readable and the demo works offline. Live samples from this PC are what the tree classifies afterwards. The jobs and page ids are a teaching projection of the trace, not a copy of the kernel run queue or the page tables. The report states that in place.

Not in this MVP: eBPF, a local LLM, Banker's algorithm, cgroups.

## Run

From `C:\Projects\TraceOS`:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m traceos
```

`python -m traceos` with no arguments opens the window. `run_dashboard.bat` does the same.

In the window:

1. **Load demo trace** is already applied at startup. Five phases, one class each. Click a row to read the explanation. The scheduler table is the same trace as jobs. Change **Frames** or **RR quantum** to rerun the algorithms.
2. **Sample this PC (10s)** records a live trace and saves `data\live.json`.
3. **CPU spike (3s)** pegs every logical CPU. Press it while a sample is running if you want the live trace to leave the normal class.
4. **Export report…** writes the markdown report.

Terminal, if you do not want the window:

```powershell
.venv\Scripts\python.exe -m traceos demo
.venv\Scripts\python.exe -m traceos collect --seconds 10 --out data\live.json
.venv\Scripts\python.exe -m traceos report data\live.json --out data\report.md
.venv\Scripts\python.exe -m pytest -q
```
