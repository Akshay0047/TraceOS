"""The demo trace classifies in phase order and the replay is internally consistent."""

from pathlib import Path

import pytest

from traceos.detect import detect_windows, holdout_accuracy, train_model
from traceos.explain import explain
from traceos.features import window_features
from traceos.replay import run_experiment
from traceos.report import render_report
from traceos.samples import load_trace, save_trace
from traceos.scenarios import demo_samples, make_window


def test_memory_window_slope_is_two_percent_per_second():
    features = window_features(make_window("memory_growth"))
    assert features["mem_slope"] == pytest.approx(2.0)
    assert window_features(make_window("spawn_storm"))["spawn_per_s"] == pytest.approx(3.0)
    assert window_features(make_window("io_heavy"))["io_mb_s"] == pytest.approx(20.0)


def test_holdout_accuracy():
    assert holdout_accuracy() >= 0.95


def test_demo_trace_labels_follow_the_five_phases():
    detections = detect_windows(demo_samples(), train_model())
    assert [item.label for item in detections] == [
        "normal",
        "cpu_saturation",
        "memory_growth",
        "spawn_storm",
        "io_heavy",
    ]
    text = explain(detections[1])
    assert "CPU scheduling" in text
    assert "Decision path" in text
    paths = {item.label: " ".join(item.rules) for item in detections}
    assert "spawn_per_s" in paths["spawn_storm"]
    assert "mem_slope" in paths["memory_growth"]
    assert "io_mb_s" in paths["io_heavy"]
    assert "cpu_max" in paths["cpu_saturation"]


def test_demo_replay_separates_policies_and_optimal_wins_or_ties():
    experiment = run_experiment(demo_samples(), frames=3, quantum=4)
    waiting = {item.key: item.avg_waiting for item in experiment.schedules}
    assert len(set(round(value, 5) for value in waiting.values())) >= 3
    faults = {item.name: item.faults for item in experiment.paging}
    assert faults["Optimal"] <= faults["FIFO"]
    assert faults["Optimal"] <= faults["LRU"]
    report = render_report(demo_samples(), detect_windows(demo_samples(), train_model()), experiment)
    assert "spawn_storm" in report
    assert "SRTF" in report


def test_trace_roundtrip(tmp_path: Path):
    path = tmp_path / "trace.json"
    save_trace(path, demo_samples(), {"host": "test"})
    loaded, meta = load_trace(path)
    assert meta["host"] == "test"
    assert loaded == demo_samples()
