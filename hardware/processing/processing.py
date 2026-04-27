"""
hardware/processing/processing.py
Reads SensorData rows from the Flask database and returns a cleaned
pandas DataFrame — the same shape the detection and scoring algos expect.

This is the DB equivalent of the old load_csv() function. The Flask app
and the hardware Pi process share the same SQLite file (app.db), so the
Pi reads data that ThingsBoard already wrote via get_device_data.py.
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ── Path setup ─────────────────────────────────────────────────────────────────
# Allows hardware scripts to import from app/backend/api/
_HERE = os.path.dirname(os.path.abspath(__file__))
_API_DIR = os.path.join(_HERE, "..", "..", "app", "backend", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

_ALGOS_DIR = os.path.join(_HERE, "..", "..", "algos")
if _ALGOS_DIR not in sys.path:
    sys.path.insert(0, _ALGOS_DIR)

from config import SLEEP_DETECTION

# Valid ranges for each sensor column — values outside these are set to NaN
SENSOR_RANGES = {
    "temperature": (-10.0, 50.0),
    "humidity": (0.0, 100.0),
    "light": (0, 1023),
    "sound": (0, 1023),
    "distance": (0, 5000),
}


def load_from_db(
    flask_app,
    device_id: int,
    hours_back: int = 12,
    start: datetime = None,
    end: datetime = None,
) -> pd.DataFrame:
    """
    Query SensorData for a device over a time window and return a cleaned
    wide-format DataFrame with columns:
        timestamp, temperature, humidity, light, sound, distance, motion

    Parameters
    ----------
    flask_app  : Flask app instance (needed for app_context)
    device_id  : int
    hours_back : int    load the last N hours (ignored if start/end provided)
    start, end : datetime  explicit UTC bounds (optional)
    """
    from models import SensorData

    if start is None and end is None:
        end = datetime.utcnow()
        start = end - timedelta(hours=hours_back)

    # ThingsBoard stores timestamps as epoch-ms BigInteger
    start_ms = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)

    with flask_app.app_context():
        rows = (
            SensorData.query.filter(
                SensorData.device_id == device_id,
                SensorData.timestamp >= start_ms,
                SensorData.timestamp <= end_ms,
            )
            .order_by(SensorData.timestamp.asc())
            .all()
        )
        # Read all attributes inside the session to avoid DetachedInstanceError
        records = [
            {
                "timestamp_ms": r.timestamp,
                "temperature": r.temperature,
                "humidity": r.humidity,
                "light": r.light,
                "sound": r.sound,
                "distance": r.distance,
                "motion": r.motion,
            }
            for r in rows
        ]

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)

    # Convert epoch-ms to UTC datetime
    df["timestamp"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
    df = df.drop(columns=["timestamp_ms"])

    # motion is stored as bool — convert to int (0/1) for the detection algo
    if "motion" in df.columns:
        df["motion"] = df["motion"].astype("Int64")  # nullable int handles None

    df = _validate_ranges(df)
    df = _fill_missing(df)
    df = _smooth(df)
    df = df.sort_values("timestamp").reset_index(drop=True)

    return df


def load_last_night(flask_app, device_id: int) -> pd.DataFrame:
    """Shortcut: load the most recent 12-hour block."""
    return load_from_db(flask_app, device_id, hours_back=12)


# ── Cleaning helpers ───────────────────────────────────────────────────────────


def _validate_ranges(df: pd.DataFrame) -> pd.DataFrame:
    """Set out-of-range sensor values to NaN."""
    for col, (lo, hi) in SENSOR_RANGES.items():
        if col not in df.columns:
            continue
        mask = (df[col] < lo) | (df[col] > hi)
        n_bad = mask.sum()
        if n_bad:
            print(f"[processing] {col}: {n_bad} out-of-range values → NaN")
        df.loc[mask, col] = np.nan
    return df


def _fill_missing(df: pd.DataFrame) -> pd.DataFrame:
    """Forward-fill then back-fill short gaps (≤5 samples)."""
    sensor_cols = [c for c in SENSOR_RANGES if c in df.columns]
    df[sensor_cols] = df[sensor_cols].ffill(limit=5).bfill(limit=5)
    return df


def _smooth(df: pd.DataFrame) -> pd.DataFrame:
    """Rolling median on analogue channels to remove ADC spike noise."""
    analogue = ["temperature", "humidity", "light", "sound", "distance"]
    for col in analogue:
        if col in df.columns:
            df[col] = df[col].rolling(window=3, min_periods=1, center=True).median()
    return df


def summary(df: pd.DataFrame) -> dict:
    """Quick stats dict — useful for debugging."""
    if df.empty:
        return {"n_rows": 0}
    duration = (df["timestamp"].max() - df["timestamp"].min()).total_seconds() / 60
    return {
        "n_rows": len(df),
        "duration_min": round(duration, 1),
        "columns": list(df.columns),
        "missing": df.isna().sum().to_dict(),
    }
