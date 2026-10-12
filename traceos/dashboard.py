"""PySide6 window: sample or load a trace, read the explanation, compare algorithms."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTabWidget,
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
        self.resize(1180, 720)
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

        stress = QGroupBox("While sampling — push the live trace off normal")
        stress_row = QHBoxLayout(stress)
        stress_row.setContentsMargins(8, 8, 8, 8)
        self.spike_btn = QPushButton("CPU spike")
        self.mem_btn = QPushButton("Memory spike")
        self.io_btn = QPushButton("Disk write")
        self.spawn_btn = QPushButton("Spawn burst")
        self.lock_btn = QPushButton("Lock order")
        for button in (self.spike_btn, self.mem_btn, self.io_btn, self.spawn_btn, self.lock_btn):
            button.setProperty("role", "stress")
            stress_row.addWidget(button)
        stress_row.addStretch(1)
        layout.addWidget(stress)

        self.summary = QLabel("Load a trace to see the result.")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("font-size: 14px; font-weight: 600; padding: 4px 0;")
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
        self.spark.setMaximumHeight(168)
        self.sample_table = _table(
            ["t", "CPU %", "Mem %", "Processes", "Born", "Write KB", "Running", "Faults", "Ctx sw"]
        )
        self.detect_table = _table(["Window", "Label", "OS concept", "Conf"])
        self.detect_table.itemSelectionChanged.connect(self._show_detection)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setFont(QFont("Consolas", 10))
        self.sched_table = _table(["Algorithm", "Avg wait", "Avg turnaround", "Avg response"])
        self.sched_table.itemSelectionChanged.connect(self._show_schedule)
        self.gantt = QTextEdit()
        self.gantt.setReadOnly(True)
        self.gantt.setFont(QFont("Consolas", 11))
        self.gantt.setMaximumHeight(72)
        self.page_table = _table(["Algorithm", "Faults", "Fault rate"])

        now = QWidget()
        now_layout = QHBoxLayout(now)
        now_layout.setContentsMargins(0, 8, 0, 0)
        story = QVBoxLayout()
        story.addWidget(self.spark)
        story.addWidget(QLabel("Click a window"))
        story.addWidget(self.detect_table, 1)
        now_layout.addLayout(story, 1)
        explain_col = QVBoxLayout()
        explain_col.addWidget(QLabel("Why this label"))
        explain_col.addWidget(self.detail, 1)
        now_layout.addLayout(explain_col, 1)

        samples_page = QWidget()
        samples_layout = QVBoxLayout(samples_page)
        samples_layout.setContentsMargins(0, 8, 0, 0)
        samples_layout.addWidget(self.sample_table)

        algorithms = QWidget()
        algo_layout = QVBoxLayout(algorithms)
        algo_layout.setContentsMargins(0, 8, 0, 0)
        compare = QSplitter(Qt.Orientation.Horizontal)
        sched_box = QWidget()
        sched_layout = QVBoxLayout(sched_box)
        sched_layout.setContentsMargins(0, 0, 0, 0)
        sched_layout.addWidget(QLabel("Scheduling — same trace as jobs"))
        sched_layout.addWidget(self.sched_table)
        page_box = QWidget()
        page_layout = QVBoxLayout(page_box)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(QLabel("Paging — same trace as page ids"))
        page_layout.addWidget(self.page_table)
        compare.addWidget(sched_box)
        compare.addWidget(page_box)
        compare.setSizes([640, 420])
        algo_layout.addWidget(compare, 1)
        algo_layout.addWidget(QLabel("Selected schedule"))
        algo_layout.addWidget(self.gantt)

        self.tabs = QTabWidget()
        self.tabs.addTab(now, "Result")
        self.tabs.addTab(algorithms, "Algorithms")
        self.tabs.addTab(samples_page, "Samples")
        layout.addWidget(self.tabs, 1)
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
        labels = "  ·  ".join(item.label.replace("_", " ") for item in self.detections)
        best = min(self.experiment.schedules, key=lambda item: item.avg_waiting)
        paging = min(self.experiment.paging, key=lambda item: item.faults)
        self.summary.setText(
            f"{labels}\nLowest wait {best.name} {best.avg_waiting:.2f}   ·   "
            f"Fewest faults {paging.name} {paging.faults}"
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
            label = detection.label + (" ?" if detection.outlier else "")
            values = [f"{detection.start}\u2013{detection.end}", label, title, f"{detection.confidence:.0%}"]
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
        self.gantt.setPlainText(format_gantt(chosen))

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
