"""The window can be built without a physical display."""

import os

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
