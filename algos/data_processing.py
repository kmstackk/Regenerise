"""
data_processing.py: sensor data cleaning, handles ingestion from CSV (hopefully thingsboard later)
and cleans data; handling noise and ensuring ranges accurate (watching for any anomolies)
"""

from enum import unique
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from config import SLEEP_DETECTION, ENVIRONMENT


# Valid sensor ranges
SENSOR_RANGES: dict = {
    "temperature": (-10.0, 50.0),  # °C
    "humidity": (0.0, 100.0),  # %RH
    "light": (0, 1023),  # ADC 10-bit
    "sound": (0, 1023),  # ADC 10-bit
    "distance": (0, 5000),  # mm (HC-SR04 or similar)
    "motion": (0, 1),  # binary
}


def load_csv(path: str) -> pd.DataFrame:
    # Load sensor data and return a cleaned DataFrame
    df = pd.read_csv(path)
    df = _standardise_columns(df)
    df = _parse_timestamps(df)
    df = _validate_ranges(df)
    df = _fill_missing(df)
    df = _smooth(df)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def _standardise_columns(df: pd.DataFrame) -> pd.DataFrame:
    # Lower case column names, rename if needed
    df.columns = [col.strip().lower() for col in df.columns]
    aliases = {
        "temp": "temperature",
        "hum": "humidity",
        "lux": "light",
        "db": "sound",
        "dist": "distance",
        "pir": "motion",
    }

    df = df.rename(columns=aliases)
    return df


def _parse_timestamps(df: pd.DataFrame) -> pd.DataFrame:
    # Convert epoch ms timestamps into pandas datetime timestamps
    if "timestamp" not in df.columns:
        raise ValueError("CSV must contain a 'timestamp' column value")

    ts = df["timestamp"]

    # check for ms vs seconds if max > 1e11 then ms
    if ts.max() > 1e11:
        df["timestamp"] = pd.to_datetime(ts, unit="ms", utc=True)
    else:
        df["timestamp"] = pd.to_datetime(ts, unit="s", utc=True)

    return df


def _validate_ranges(df: pd.DataFrame) -> pd.DataFrame:
    # Set range readings to NaN and log how many were dropped
    for col, (lo, hi) in SENSOR_RANGES.items():
        if col not in df.columns:
            continue
        mask = (df[col] < lo) | (df[col] > hi)
        n_bad = mask.sum()
        if n_bad:
            print(f"[validation] {col}: {n_bad} out of range values -> NaN")
        df.loc[mask, col] = np.nan
    return df


def _fill_missing(df: pd.DataFrame) -> pd.DataFrame:
    # Forward fill then backward fill any short gaps of less than 5 samples where sensor stopped working
    # for short time but keep any gaps more than 5 samples where sensor stopped working altogether
    sensor_cols = [col for col in SENSOR_RANGES if col in df.columns]
    df[sensor_cols] = df[sensor_cols].ffill(limit=5).bfill(limit=5)
    return df


def _smooth(df: pd.DataFrame) -> pd.DataFrame:
    # Apply a rolling median to reduce any spike noise on analogue sensors
    analogue = ["temperature", "humidity", "light", "sound", "distance"]
    for col in analogue:
        if col in df.columns:
            df[col] = df[col].rolling(window=3, min_periods=1, center=True).median()
    return df


# Nightly session detection
def segment_nights(df: pd.DataFrame) -> list[pd.DataFrame]:
    # Split multiday dataframe into individual nightly sessions, each night is assumed to
    # follow 8pm - 12pm the next day and then returns a list of per night dataframes

    df = df.copy()
    df["date"] = df["timestamp"].dt.tz_convert("Europe/London").dt.date

    nights = []
    unique_dates = sorted(df["date"].unique())

    for d in unique_dates:
        night_start = pd.Timestamp(d, tz="Europe/London") + pd.Timedelta(hours=20)
        night_end = night_start + pd.Timedelta(hours=16)
        mask = (df["timestamp"] >= night_start) & (df["timestamp"] < night_end)
        night_df = df[mask].copy()
        if len(night_df) >= 10:  # minimum viable session
            nights.append(night_df)
    return nights


def summary_stats(df: pd.DataFrame) -> dict:
    # quick dict stats from a cleaned data frame in case of debugging
    stats = {
        "n_rows": len(df),
        "duration_min": (df["timestamp"].max() - df["timestamp"].min()).total_seconds()
        / 60
        if len(df) > 1
        else 0,
        "columns": list(df.columns),
    }
    for col in SENSOR_RANGES:
        if col in df.columns:
            stats[col] = {
                "mean": round(df[col].mean(), 2),
                "min": round(df[col].min(), 2),
                "max": round(df[col].max(), 2),
                "missing": int(df[col].isna().sum()),
            }
    return stats
