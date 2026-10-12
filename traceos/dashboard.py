"""PySide6 window: sample or load a trace, read the explanation, compare algorithms."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .collect import Collector, host_meta
from .detect import detect_windows, ensure_model
from .explain import explain
from .replay import run_experiment
from .report import render_html, render_report
from .samples import Sample, load_trace, save_trace
from .scenarios import demo_samples
from .schedulers import format_gantt
from .paths import DATA
from .workloads import burst_io, burn_cpu, contained_lock_order, grow_memory, spawn_burst

_LABEL_COLOR = {
    "normal": "#5c6b7a",
    "cpu_saturation": "#b03a2e",
    "memory_growth": "#6c3483",
    "spawn_storm": "#b9770e",
    "io_heavy": "#1a5276",
}


class _SampleBridge(QObject):
    """Carries a live sample from the worker thread back to the window."""

    ready = Signal(int, object)


class Spark(QWidget):
    """CPU and memory, each stretched to its own range so a small change is visible."""

    def __init__(self) -> None:
        super().__init__()
        self.cpu: list[float] = []
        self.mem: list[float] = []
        self.focus: tuple[int, int] | None = None
        self.setMinimumHeight(220)

    def set_series(self, cpu: list[float], mem: list[float]) -> None:
        self.cpu = cpu
        self.mem = mem
        self.update()

    def set_focus(self, start: int, end: int) -> None:
        self.focus = (start, end)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        rect = self.rect().adjusted(52, 12, -52, -28)
        if len(self.cpu) < 2 or len(self.mem) < 2:
            painter.setPen(QColor("#8b9aab"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Waiting for samples")
            return
        cpu_lo, cpu_hi = _bounds(self.cpu)
        mem_lo, mem_hi = _bounds(self.mem)
        if self.focus is not None and len(self.cpu) > 1:
            start, end = self.focus
            span = len(self.cpu) - 1
            x0 = rect.left() + rect.width() * max(0, start) / span
            x1 = rect.left() + rect.width() * min(span, end) / span
            painter.fillRect(int(x0), rect.top(), max(2, int(x1 - x0)), rect.height(), QColor(31, 78, 121, 28))
        painter.setPen(QPen(QColor("#e1e8ef")))
        for step in range(5):
            y = rect.bottom() - rect.height() * step / 4
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))
            painter.setPen(QColor("#b03a2e"))
            painter.drawText(4, int(y) + 4, f"{cpu_lo + (cpu_hi - cpu_lo) * step / 4:.0f}")
            painter.setPen(QColor("#1f4e79"))
            label = f"{mem_lo + (mem_hi - mem_lo) * step / 4:.0f}"
            painter.drawText(rect.right() + 8, int(y) + 4, label)
            painter.setPen(QPen(QColor("#e1e8ef")))
        _stroke(painter, rect, self.cpu, cpu_lo, cpu_hi, QColor("#b03a2e"))
        _stroke(painter, rect, self.mem, mem_lo, mem_hi, QColor("#1f4e79"))
        painter.setPen(QColor("#b03a2e"))
        painter.drawText(rect.left(), self.height() - 8, f"CPU  {min(self.cpu):.0f}–{max(self.cpu):.0f}%")
        painter.setPen(QColor("#1f4e79"))
        painter.drawText(rect.left() + 120, self.height() - 8, f"Memory  {min(self.mem):.1f}–{max(self.mem):.1f}%")


def _bounds(values: list[float]) -> tuple[float, float]:
    lo, hi = min(values), max(values)
    span = hi - lo
    if span < 0.5:
        pad = 1.0
    else:
        pad = span * 0.2
    return lo - pad, hi + pad


def _stroke(painter: QPainter, rect, values: list[float], lo: float, hi: float, color: QColor) -> None:
    if len(values) < 2 or hi <= lo:
        return
    painter.setPen(QPen(color, 2.5))
    last = None
    span = len(values) - 1
    for index, value in enumerate(values):
        x = rect.left() + rect.width() * index / span
        y = rect.bottom() - rect.height() * (value - lo) / (hi - lo)
        point = (x, y)
        if last is not None:
            painter.drawLine(int(last[0]), int(last[1]), int(point[0]), int(point[1]))
        painter.setBrush(color)
        painter.drawEllipse(int(x) - 3, int(y) - 3, 6, 6)
        last = point
    painter.setBrush(Qt.BrushStyle.NoBrush)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Trace OS")
        self.resize(1200, 780)
        self.samples: list[Sample] = []
        self.detections = []
        self.experiment = None
        self._collector: Collector | None = None
        self._remaining = 0
        self._generation = 0
        self._sample_thread: threading.Thread | None = None
        self._bridge = _SampleBridge(self)
        self._bridge.ready.connect(self._on_sample)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        title = QLabel("Trace OS")
        title.setStyleSheet("font-size: 20px; font-weight: 650;")
        layout.addWidget(title)

        buttons = QHBoxLayout()
        self.demo_btn = QPushButton("Demo trace")
        self.live_btn = QPushButton("Sample this PC (10s)")
        self.open_btn = QPushButton("Open…")
        self.save_btn = QPushButton("Export…")
        for button in (self.demo_btn, self.live_btn, self.open_btn, self.save_btn):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(QLabel("Frames"))
        self.frames = QSpinBox()
        self.frames.setRange(1, 8)
        self.frames.setValue(3)
        buttons.addWidget(self.frames)
        buttons.addWidget(QLabel("RR quantum"))
        self.quantum = QSpinBox()
        self.quantum.setRange(1, 10)
        self.quantum.setValue(4)
        buttons.addWidget(self.quantum)
        layout.addLayout(buttons)

        stress_row = QHBoxLayout()
        stress_row.addWidget(QLabel("During a sample"))
        self.spike_btn = QPushButton("CPU spike")
        self.mem_btn = QPushButton("Memory spike")
        self.io_btn = QPushButton("Disk write")
        self.spawn_btn = QPushButton("Spawn burst")
        self.lock_btn = QPushButton("Lock order")
        for button in (self.spike_btn, self.mem_btn, self.io_btn, self.spawn_btn, self.lock_btn):
            button.setProperty("role", "stress")
            stress_row.addWidget(button)
        stress_row.addStretch(1)
        layout.addLayout(stress_row)

        self.summary = QLabel("")
        self.summary.setStyleSheet("color: #3d4f63;")
        layout.addWidget(self.summary)

        self.demo_btn.clicked.connect(self.load_demo)
        self.live_btn.clicked.connect(self.start_live)
        self.open_btn.clicked.connect(self.open_trace)
        self.spike_btn.clicked.connect(self.spike)
        self.mem_btn.clicked.connect(
            lambda: self._stress("Memory spike running — resident set climbs for 3 seconds.", lambda: grow_memory(3), "Memory spike finished.")
        )
        self.io_btn.clicked.connect(
            lambda: self._stress("Disk write running for 3 seconds.", lambda: burst_io(3), "Disk write finished.")
        )
        self.spawn_btn.clicked.connect(
            lambda: self._stress("Spawn burst running.", lambda: spawn_burst(3), "Spawn burst finished.")
        )
        self.lock_btn.clicked.connect(self.lock_order)
        self.save_btn.clicked.connect(self.export_report)
        self.frames.valueChanged.connect(lambda _v: self._recompute())
        self.quantum.valueChanged.connect(lambda _v: self._recompute())

        self.spark = Spark()
        layout.addWidget(self.spark, 2)

        self.sample_table = _table(
            ["t", "CPU %", "Mem %", "Processes", "Born", "Write KB", "Running", "Faults", "Ctx sw"]
        )
        self.sample_table.setVisible(False)
        self.sample_table.setMaximumHeight(150)
        self.samples_btn = QPushButton("Samples")
        self.samples_btn.setCheckable(True)
        self.samples_btn.setProperty("role", "stress")
        self.samples_btn.toggled.connect(self.sample_table.setVisible)
        buttons.addWidget(self.samples_btn)

        self.detect_table = _table(["Window", "What happened", "OS concept", "Conf"])
        self.detect_table.itemSelectionChanged.connect(self._show_detection)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(QFont("Segoe UI", 10))
        self.sched_table = _table(["Algorithm", "Avg wait", "Turnaround", "Response"])
        self.sched_table.itemSelectionChanged.connect(self._show_schedule)
        self.gantt = QTextEdit()
        self.gantt.setReadOnly(True)
        self.gantt.setFont(QFont("Consolas", 10))
        self.gantt.setMaximumHeight(52)
        self.page_table = _table(["Algorithm", "Faults", "Fault rate"])

        body = QHBoxLayout()
        body.setSpacing(16)
        windows = QVBoxLayout()
        windows.addWidget(_heading("Windows"))
        windows.addWidget(self.detect_table)
        windows.addStretch(1)
        explain_col = QVBoxLayout()
        explain_col.addWidget(_heading("Explanation"))
        explain_col.addWidget(self.detail, 1)
        algorithms = QVBoxLayout()
        algorithms.addWidget(_heading("Scheduling"))
        algorithms.addWidget(self.sched_table)
        algorithms.addWidget(self.gantt)
        algorithms.addWidget(_heading("Paging"))
        algorithms.addWidget(self.page_table)
        algorithms.addStretch(1)
        body.addLayout(windows, 4)
        body.addLayout(explain_col, 5)
        body.addLayout(algorithms, 4)
        layout.addLayout(body, 3)
        layout.addWidget(self.sample_table)
        self.load_demo()

    def load_demo(self) -> None:
        self._stop_live()
        self.samples = demo_samples()
        self._recompute()
        self.statusBar().showMessage("Demo trace: normal, CPU saturation, memory growth, spawn storm, heavy I/O.")

    def open_trace(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(self, "Open trace", str(DATA), "Trace (*.json)")
        if not path:
            return
        self._stop_live()
        self.samples, _meta = load_trace(path)
        self._recompute()
        self.statusBar().showMessage(path)

    def start_live(self) -> None:
        self._stop_live()
        self.samples = []
        self._collector = Collector()
        self._remaining = 10
        self.live_btn.setEnabled(False)
        self._timer.start(1000)
        self.statusBar().showMessage("Sampling 10 s. A CPU spike during this window is the clearest live class.")
        self._recompute()

    def spike(self) -> None:
        self._stress("CPU spike running for 3 seconds.", lambda: burn_cpu(3), "CPU spike finished.")

    def _stress(self, message: str, work, done: str) -> None:
        self.statusBar().showMessage(message)
        generation = self._generation

        def run() -> None:
            try:
                work()
            except Exception as exc:
                self._bridge.ready.emit(generation, f"Stress failed: {exc}")
                return
            self._bridge.ready.emit(generation, done)

        threading.Thread(target=run, name="traceos-stress", daemon=True).start()

    def lock_order(self) -> None:
        def work() -> None:
            text = contained_lock_order()
            self._bridge.ready.emit(self._generation, text)

        self.statusBar().showMessage("Two threads take locks in opposite orders, then give up.")
        threading.Thread(target=work, name="traceos-locks", daemon=True).start()

    def export_report(self) -> None:
        if not self.samples:
            return
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Export report",
            str(DATA / "report.md"),
            "Markdown (*.md);;HTML (*.html)",
        )
        if not path:
            return
        text = render_report(self.samples, self.detections, self.experiment)
        if path.lower().endswith(".html"):
            text = render_html(text)
        from pathlib import Path

        Path(path).write_text(text, encoding="utf-8")
        self.statusBar().showMessage(f"Wrote {path}")

    def _tick(self) -> None:
        if self._collector is None:
            return
        thread = self._sample_thread
        if thread is not None and thread.is_alive():
            return
        collector = self._collector
        generation = self._generation

        def work() -> None:
            try:
                sample: object = collector.sample()
            except Exception as exc:
                sample = exc
            self._bridge.ready.emit(generation, sample)

        self._sample_thread = threading.Thread(target=work, name="traceos-sample", daemon=True)
        self._sample_thread.start()

    def _on_sample(self, generation: int, sample: object) -> None:
        if generation != self._generation:
            return
        if isinstance(sample, str):
            self.statusBar().showMessage(sample)
            return
        if self._collector is None:
            return
        if isinstance(sample, Exception):
            self._stop_live()
            self.statusBar().showMessage("Sample failed.")
            return
        self.samples.append(sample)
        self._remaining -= 1
        self._recompute()
        self.statusBar().showMessage(f"Sampling \u2014 {self._remaining} s left")
        if self._remaining <= 0:
            self._stop_live()
            path = DATA / "live.json"
            save_trace(path, self.samples, host_meta())
            self.statusBar().showMessage(f"Saved {path}")

    def _stop_live(self) -> None:
        self._generation += 1
        self._timer.stop()
        self._collector = None
        self.live_btn.setEnabled(True)

    def _recompute(self) -> None:
        self.detections = detect_windows(self.samples, ensure_model()) if self.samples else []
        self.experiment = run_experiment(self.samples, self.frames.value(), self.quantum.value())
        self._fill_samples()
        self._fill_detections()
        self._fill_schedules()
        self._fill_paging()
        self.spark.set_series(
            [sample.cpu_percent for sample in self.samples],
            [sample.mem_percent for sample in self.samples],
        )
        self._fill_summary()

    def _fill_summary(self) -> None:
        if not self.detections or self.experiment is None:
            self.summary.setText("No window yet. A window is five samples.")
            return
        best = min(self.experiment.schedules, key=lambda item: item.avg_waiting)
        paging = min(self.experiment.paging, key=lambda item: item.faults)
        self.summary.setText(
            f"Lowest waiting time: {best.name} {best.avg_waiting:.2f}"
            f"      Fewest page faults: {paging.name} {paging.faults}"
        )

    def _fill_samples(self) -> None:
        table = self.sample_table
        table.setRowCount(len(self.samples))
        for row, sample in enumerate(self.samples):
            values = [
                f"{sample.t:.1f}",
                f"{sample.cpu_percent:.0f}",
                f"{sample.mem_percent:.1f}",
                str(sample.proc_count),
                str(sample.proc_born),
                f"{sample.write_bytes / 1024:.0f}",
                str(sample.running),
                str(sample.page_faults),
                str(sample.ctx_switches),
            ]
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        if self.samples:
            table.scrollToBottom()

    def _fill_detections(self) -> None:
        from .explain import CONCEPTS

        table = self.detect_table
        table.blockSignals(True)
        table.setRowCount(len(self.detections))
        pick = 0
        for row, detection in enumerate(self.detections):
            if detection.label != "normal":
                pick = row
                break
        for row, detection in enumerate(self.detections):
            title = CONCEPTS.get(detection.label, ("",))[0]
            label = detection.label.replace("_", " ") + (" ?" if detection.outlier else "")
            values = [f"{detection.start}\u2013{detection.end}", label, title, f"{detection.confidence:.0%}"]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 1:
                    item.setForeground(QColor(_LABEL_COLOR.get(detection.label, "#222")))
                table.setItem(row, column, item)
        if self.detections:
            table.selectRow(pick)
        table.blockSignals(False)
        _fit(table)
        self._show_detection()

    def _fill_schedules(self) -> None:
        table = self.sched_table
        schedules = self.experiment.schedules if self.experiment else ()
        table.blockSignals(True)
        table.setRowCount(len(schedules))
        best = 0
        if schedules:
            best = min(range(len(schedules)), key=lambda i: schedules[i].avg_waiting)
        for row, item in enumerate(schedules):
            values = [
                item.name,
                f"{item.avg_waiting:.2f}",
                f"{item.avg_turnaround:.2f}",
                f"{item.avg_response:.2f}",
            ]
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        if schedules:
            table.selectRow(best)
        table.blockSignals(False)
        _fit(table)
        self._show_schedule()

    def _fill_paging(self) -> None:
        table = self.page_table
        paging = self.experiment.paging if self.experiment else ()
        table.setRowCount(len(paging))
        for row, item in enumerate(paging):
            for column, value in enumerate((item.name, str(item.faults), f"{item.fault_rate:.0%}")):
                table.setItem(row, column, QTableWidgetItem(value))
        _fit(table)

    def _show_detection(self) -> None:
        row = self.detect_table.currentRow()
        if row < 0 or row >= len(self.detections):
            self.detail.setPlainText("Click a window. Each window is five samples.")
            return
        chosen = self.detections[row]
        self.spark.set_focus(chosen.start, chosen.end)
        self.detail.setPlainText(explain(chosen))

    def _show_schedule(self) -> None:
        if self.experiment is None or not self.experiment.schedules:
            self.gantt.setPlainText("")
            return
        row = self.sched_table.currentRow()
        if row < 0:
            row = 0
        chosen = self.experiment.schedules[row]
        self.gantt.setPlainText(format_gantt(chosen))

    def closeEvent(self, event) -> None:
        self._stop_live()
        thread = self._sample_thread
        if thread is not None:
            thread.join(timeout=1.0)
        super().closeEvent(event)


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    label.setStyleSheet("font-weight: 650;")
    return label


def _fit(table: QTableWidget) -> None:
    table.resizeRowsToContents()
    header = table.horizontalHeader().height()
    if header < 24:
        header = 28
    row_h = table.rowHeight(0) if table.rowCount() else 24
    if row_h < 18:
        row_h = 24
    height = header + 8 + row_h * table.rowCount()
    table.setFixedHeight(height)


def _table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.setAlternatingRowColors(True)
    return table


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(
        """
        QWidget { background: #f4f7fa; color: #1c2833; font-size: 13px; }
        QPushButton { background: #1f4e79; color: white; border: none; padding: 6px 12px; border-radius: 4px; }
        QPushButton:hover { background: #2d6aa3; }
        QPushButton:disabled { background: #9aa8b5; }
        QPushButton[role="stress"] { background: #e7eef5; color: #1c2833; }
        QPushButton[role="stress"]:hover { background: #d3e0ec; }
        QTableWidget { background: white; alternate-background-color: #f7fafc; gridline-color: #e6edf3; }
        QHeaderView::section { background: #e7eef5; padding: 4px; border: none; font-weight: 600; }
        QTextEdit, QSpinBox, QTabWidget::pane { background: white; }
        QTabBar::tab { background: #e7eef5; padding: 6px 14px; margin-right: 2px; }
        QTabBar::tab:selected { background: white; font-weight: 600; }
        QGroupBox { font-weight: 600; border: 1px solid #d5dee8; border-radius: 6px; margin-top: 8px; }
        QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
        QStatusBar { background: #e7eef5; }
        """
    )
    window = MainWindow()
    window.show()
    return app.exec()
