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
    QSpinBox,
    QSplitter,
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
from .report import render_report
from .samples import Sample, load_trace, save_trace
from .scenarios import demo_samples
from .schedulers import format_gantt
from .paths import DATA
from .workloads import burn_cpu

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
    def __init__(self) -> None:
        super().__init__()
        self.cpu: list[float] = []
        self.mem: list[float] = []
        self.setMinimumHeight(150)

    def set_series(self, cpu: list[float], mem: list[float]) -> None:
        self.cpu = cpu
        self.mem = mem
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        rect = self.rect().adjusted(36, 16, -12, -22)
        painter.setPen(QPen(QColor("#e1e8ef")))
        for step in range(5):
            y = rect.bottom() - rect.height() * step / 4
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))
            painter.setPen(QColor("#8b9aab"))
            painter.drawText(4, int(y) + 4, f"{step * 25}")
            painter.setPen(QPen(QColor("#e1e8ef")))
        _stroke(painter, rect, self.cpu, QColor("#b03a2e"))
        _stroke(painter, rect, self.mem, QColor("#1f4e79"))
        painter.setPen(QColor("#b03a2e"))
        painter.drawText(rect.left(), self.height() - 6, "CPU %")
        painter.setPen(QColor("#1f4e79"))
        painter.drawText(rect.left() + 56, self.height() - 6, "Memory %")


def _stroke(painter: QPainter, rect, values: list[float], color: QColor) -> None:
    if len(values) < 2:
        return
    painter.setPen(QPen(color, 2))
    last = None
    span = len(values) - 1
    for index, value in enumerate(values):
        x = rect.left() + rect.width() * index / span
        y = rect.bottom() - rect.height() * max(0.0, min(100.0, value)) / 100
        point = (x, y)
        if last is not None:
            painter.drawLine(int(last[0]), int(last[1]), int(point[0]), int(point[1]))
        last = point


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Trace OS")
        self.resize(1180, 760)
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
        title.setStyleSheet("font-size: 22px; font-weight: 650;")
        subtitle = QLabel("Observe  \u2192  Detect  \u2192  Explain  \u2192  Experiment  \u2192  Report")
        subtitle.setStyleSheet("color: #3d4f63;")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        buttons = QHBoxLayout()
        self.demo_btn = QPushButton("Load demo trace")
        self.live_btn = QPushButton("Sample this PC (10s)")
        self.open_btn = QPushButton("Open trace\u2026")
        self.spike_btn = QPushButton("CPU spike (3s)")
        self.save_btn = QPushButton("Export report\u2026")
        for button in (self.demo_btn, self.live_btn, self.open_btn, self.spike_btn, self.save_btn):
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

        self.demo_btn.clicked.connect(self.load_demo)
        self.live_btn.clicked.connect(self.start_live)
        self.open_btn.clicked.connect(self.open_trace)
        self.spike_btn.clicked.connect(self.spike)
        self.save_btn.clicked.connect(self.export_report)
        self.frames.valueChanged.connect(lambda _v: self._recompute())
        self.quantum.valueChanged.connect(lambda _v: self._recompute())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.spark = Spark()
        left_layout.addWidget(self.spark)
        self.sample_table = _table(["t", "CPU %", "Mem %", "Processes", "Born", "Write KB", "Running"])
        left_layout.addWidget(self.sample_table)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Detections"))
        self.detect_table = _table(["Window", "Label", "OS concept"])
        self.detect_table.itemSelectionChanged.connect(self._show_detection)
        right_layout.addWidget(self.detect_table, 2)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(QFont("Consolas", 10))
        right_layout.addWidget(self.detail, 3)
        right_layout.addWidget(QLabel("Scheduling  (derived jobs)"))
        self.sched_table = _table(["Algorithm", "Avg wait", "Avg turnaround", "Avg response"])
        self.sched_table.itemSelectionChanged.connect(self._show_schedule)
        right_layout.addWidget(self.sched_table, 2)
        self.gantt = QTextEdit()
        self.gantt.setReadOnly(True)
        self.gantt.setFont(QFont("Consolas", 10))
        self.gantt.setMaximumHeight(140)
        right_layout.addWidget(self.gantt)
        right_layout.addWidget(QLabel("Paging"))
        self.page_table = _table(["Algorithm", "Faults", "Fault rate"])
        right_layout.addWidget(self.page_table, 2)
        splitter.addWidget(right)
        splitter.setSizes([640, 520])
        layout.addWidget(splitter, 1)
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
        self.statusBar().showMessage("Pegging every logical CPU for 3 seconds.")
        threading.Thread(target=lambda: burn_cpu(3), daemon=True).start()

    def export_report(self) -> None:
        if not self.samples:
            return
        path, _selected = QFileDialog.getSaveFileName(self, "Export report", str(DATA / "report.md"), "Markdown (*.md)")
        if not path:
            return
        text = render_report(self.samples, self.detections, self.experiment)
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
        if generation != self._generation or self._collector is None:
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
            values = [f"{detection.start}\u2013{detection.end}", detection.label, title]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 1:
                    item.setForeground(QColor(_LABEL_COLOR.get(detection.label, "#222")))
                table.setItem(row, column, item)
        if self.detections:
            table.selectRow(pick)
        table.blockSignals(False)
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
        self._show_schedule()

    def _fill_paging(self) -> None:
        table = self.page_table
        paging = self.experiment.paging if self.experiment else ()
        table.setRowCount(len(paging))
        for row, item in enumerate(paging):
            for column, value in enumerate((item.name, str(item.faults), f"{item.fault_rate:.0%}")):
                table.setItem(row, column, QTableWidgetItem(value))

    def _show_detection(self) -> None:
        row = self.detect_table.currentRow()
        if row < 0 or row >= len(self.detections):
            self.detail.setPlainText("Load a trace or sample this PC. A window is five samples.")
            return
        self.detail.setPlainText(explain(self.detections[row]))

    def _show_schedule(self) -> None:
        if self.experiment is None or not self.experiment.schedules:
            self.gantt.setPlainText("")
            return
        row = self.sched_table.currentRow()
        if row < 0:
            row = 0
        chosen = self.experiment.schedules[row]
        jobs = "   ".join(
            f"{job.jid} arr {job.arrival} burst {job.burst} pri {job.priority}" for job in self.experiment.jobs
        )
        lines = [jobs, "", format_gantt(chosen)]
        for job in chosen.jobs:
            lines.append(
                f"{job.jid:<4} start {job.start:<4} finish {job.finish:<4} wait {job.waiting:<4} turn {job.turnaround}"
            )
        self.gantt.setPlainText("\n".join(lines))

    def closeEvent(self, event) -> None:
        self._stop_live()
        thread = self._sample_thread
        if thread is not None:
            thread.join(timeout=1.0)
        super().closeEvent(event)


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
        QTableWidget { background: white; alternate-background-color: #f7fafc; gridline-color: #e6edf3; }
        QHeaderView::section { background: #e7eef5; padding: 4px; border: none; font-weight: 600; }
        QTextEdit, QSpinBox { background: white; }
        QStatusBar { background: #e7eef5; }
        """
    )
    window = MainWindow()
    window.show()
    return app.exec()
