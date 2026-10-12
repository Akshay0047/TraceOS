"""Decision tree over window features. The same function trains, scores, and explains."""

from __future__ import annotations

from dataclasses import dataclass

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.tree import DecisionTreeClassifier

from .features import FEATURE_NAMES, vector, window_features, iter_windows
from .paths import MODEL_PATH
from .samples import Sample
from .scenarios import synthesize

_MODEL: DecisionTreeClassifier | None = None
_OUTLIER: IsolationForest | None = None


@dataclass(frozen=True, slots=True)
class Detection:
    start: int
    end: int
    label: str
    features: dict[str, float]
    rules: tuple[str, ...]
    confidence: float = 1.0
    outlier: bool = False


def train_model(seed: int = 0) -> DecisionTreeClassifier:
    rows, labels = synthesize(seed=seed)
    model = DecisionTreeClassifier(max_depth=4, min_samples_leaf=3, random_state=seed)
    model.fit(rows, labels)
    return model


def save_model(model: DecisionTreeClassifier, path=MODEL_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"version": 1, "features": list(FEATURE_NAMES), "model": model}, path)


def load_model(path=MODEL_PATH) -> DecisionTreeClassifier:
    blob = joblib.load(path)
    if list(blob["features"]) != list(FEATURE_NAMES):
        raise ValueError("saved model uses different features; run traceos train")
    return blob["model"]


def ensure_model() -> DecisionTreeClassifier:
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    if MODEL_PATH.exists():
        _MODEL = load_model()
    else:
        _MODEL = train_model()
        save_model(_MODEL)
    return _MODEL


def decision_rules(model: DecisionTreeClassifier, values: np.ndarray) -> list[str]:
    tree = model.tree_
    node = 0
    rules: list[str] = []
    while tree.feature[node] != -2:
        index = int(tree.feature[node])
        threshold = float(tree.threshold[node])
        value = float(values[index])
        name = FEATURE_NAMES[index]
        if value <= threshold:
            rules.append(f"{name} = {_fmt(name, value)} <= {_fmt(name, threshold)}")
            node = int(tree.children_left[node])
        else:
            rules.append(f"{name} = {_fmt(name, value)} > {_fmt(name, threshold)}")
            node = int(tree.children_right[node])
    return rules


def _fmt(name: str, value: float) -> str:
    if name in {"cpu_mean", "cpu_max", "mem_slope", "running_mean"}:
        return f"{value:.1f}"
    if name == "spawn_per_s":
        return f"{value:.2f}/s"
    if name == "io_mb_s":
        return f"{value:.2f} MB/s"
    return f"{value:.3g}"


def ensure_outlier() -> IsolationForest:
    """Flags windows that do not look like the five synthetic classes."""
    global _OUTLIER
    if _OUTLIER is None:
        rows, _labels = synthesize(seed=0)
        model = IsolationForest(n_estimators=80, contamination=0.02, random_state=0)
        model.fit(rows)
        _OUTLIER = model
    return _OUTLIER


def detect_windows(samples: list[Sample], model: DecisionTreeClassifier | None = None) -> list[Detection]:
    model = model or ensure_model()
    outlier_model = ensure_outlier()
    found: list[Detection] = []
    for start, window in iter_windows(samples):
        feats = window_features(window)
        row = np.asarray([vector(feats)], dtype=float)
        label = str(model.predict(row)[0])
        proba = model.predict_proba(row)[0]
        confidence = float(proba.max()) if len(proba) else 1.0
        unseen = int(outlier_model.predict(row)[0]) == -1
        found.append(
            Detection(
                start=start,
                end=start + len(window) - 1,
                label=label,
                features=feats,
                rules=tuple(decision_rules(model, row[0])),
                confidence=confidence,
                outlier=unseen,
            )
        )
    return found


def holdout_accuracy(seed: int = 1) -> float:
    model = train_model(seed=0)
    rows, labels = synthesize(seed=seed)
    return float(model.score(rows, labels))
