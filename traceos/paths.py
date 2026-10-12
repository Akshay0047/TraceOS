"""Locations that belong to this checkout, not to the machine being observed."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MODEL_PATH = DATA / "model.joblib"
