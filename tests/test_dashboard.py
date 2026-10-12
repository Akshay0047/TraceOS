"""The window can be built without a physical display."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_dashboard_loads_demo_trace():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from traceos.dashboard import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.detect_table.rowCount() == 5
    assert window.sched_table.rowCount() == 5
    assert window.page_table.rowCount() == 3
    assert "CPU scheduling" in window.detail.toPlainText()
    window.close()
    app.processEvents()


def test_live_samples_stay_on_a_one_second_cadence():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from traceos.dashboard import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.start_live()
    deadline = time.perf_counter() + 5
    while len(window.samples) < 2 and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.02)
    window._stop_live()
    app.processEvents()
    assert len(window.samples) >= 2
    gap = window.samples[1].t - window.samples[0].t
    assert gap < 2.5
    window.close()
    app.processEvents()
