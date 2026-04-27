"""
hardware/detection/detection.py
Per-sample sleep/wake state machine and nightly metric extraction.
Operates on the DataFrame produced by hardware/processing/processing.py.
"""

import sys
import os
import pandas as pd
import numpy as np
from datetime import datetime

_ALGOS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "algos"
)
if _ALGOS_DIR not in sys.path:
    sys.path.insert(0, _ALGOS_DIR)

from config import SLEEP_DETECTION, RESTLESSNESS

# State labels
AWAKE = "AWAKE"
SLEEP = "SLEEP"
UNCERTAIN = "UNCERTAIN"


# ── Per-row sensor votes ───────────────────────────────────────────────────────
# Each returns 0.0 (awake) … 1.0 (asleep)


def _vote_light(val) -> float:
    if pd.isna(val):
        return 0.5
    thr = SLEEP_DETECTION["light_sleep_threshold"]
    wake = SLEEP_DETECTION["light_awake_threshold"]
    if val <= thr:
        return 1.0
    if val >= wake:
        return 0.0
    return 1.0 - (val - thr) / (wake - thr)


def _vote_sound(val) -> float:
    if pd.isna(val):
        return 0.5
    thr = SLEEP_DETECTION["sound_sleep_threshold"]
    noise = SLEEP_DETECTION["sound_change_occur_threshold"]
    if val <= thr:
        return 1.0
    if val >= noise:
        return 0.0
    return 1.0 - (val - thr) / (noise - thr)


def _vote_motion(val) -> float:
    if pd.isna(val):
        return 0.5
    return 0.0 if int(val) >= SLEEP_DETECTION["motion_active_threshold"] else 1.0


def _vote_distance(series: pd.Series, idx: int) -> float:
    if pd.isna(series.iloc[idx]):
        return 0.5
    window_start = max(0, idx - 10)
    ref = series.iloc[window_start:idx].median()
    if pd.isna(ref):
        return 0.5
    delta = abs(series.iloc[idx] - ref)
    thr = SLEEP_DETECTION["distance_change_threshold"]
    if delta <= thr:
        return 1.0
    if delta >= thr * 3:
        return 0.0
    return 1.0 - (delta - thr) / (thr * 2)


# ── Main detection ─────────────────────────────────────────────────────────────


def detect_sleep_states(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds columns to df:
      sleep_score        0.0–1.0  (higher = more sleep-like)
      sleep_score_smooth smoothed version used for final labelling
      state              SLEEP | AWAKE | UNCERTAIN
      is_sleep           bool convenience flag

    Returns modified DataFrame.
    """
    if df.empty:
        return df

    df = df.copy()
    has = {c: c in df.columns for c in ["light", "sound", "motion", "distance"]}

    scores = []
    for i in range(len(df)):
        row = df.iloc[i]
        votes = []
        if has["light"]:
            votes.append((_vote_light(row["light"]), 2.0))
        if has["sound"]:
            votes.append((_vote_sound(row["sound"]), 2.0))
        if has["motion"]:
            votes.append((_vote_motion(row["motion"]), 3.0))  # strongest indicator
        if has["distance"]:
            votes.append((_vote_distance(df["distance"], i), 2.0))

        if not votes:
            scores.append(0.5)
            continue

        weighted = sum(v * w for v, w in votes)
        total_w = sum(w for _, w in votes)
        scores.append(weighted / total_w)

    df["sleep_score"] = scores

    # Smooth over a rolling window (~¼ of min_sleep_window)
    window_samples = max(
        3,
        int(
            SLEEP_DETECTION["min_sleep_window_min"]
            * 60
            / SLEEP_DETECTION["sample_interval_secs"]
            / 4
        ),
    )
    df["sleep_score_smooth"] = (
        df["sleep_score"].rolling(window_samples, min_periods=1, center=True).mean()
    )

    df["state"] = df["sleep_score_smooth"].apply(_label)
    df["is_sleep"] = df["state"] == SLEEP
    return df


def _label(score: float) -> str:
    if score >= 0.65:
        return SLEEP
    if score <= 0.40:
        return AWAKE
    return UNCERTAIN


# ── Nightly metric extraction ──────────────────────────────────────────────────


def extract_sleep_periods(df: pd.DataFrame) -> list[dict]:
    """
    Return list of continuous state blocks:
      {"state", "start", "end", "duration_min"}
    """
    if "state" not in df.columns or df.empty:
        return []

    periods = []
    current_state = df["state"].iloc[0]
    start_ts = df["timestamp"].iloc[0]

    for i in range(1, len(df)):
        s = df["state"].iloc[i]
        if s != current_state:
            end_ts = df["timestamp"].iloc[i]
            dur = (end_ts - start_ts).total_seconds() / 60
            periods.append(
                {
                    "state": current_state,
                    "start": start_ts,
                    "end": end_ts,
                    "duration_min": round(dur, 1),
                }
            )
            current_state = s
            start_ts = end_ts

    end_ts = df["timestamp"].iloc[-1]
    dur = (end_ts - start_ts).total_seconds() / 60
    periods.append(
        {
            "state": current_state,
            "start": start_ts,
            "end": end_ts,
            "duration_min": round(dur, 1),
        }
    )
    return periods


def sleep_onset_and_wake(periods: list[dict]) -> tuple:
    """Return (sleep_onset_ts, wake_ts) from the period list."""
    min_min = SLEEP_DETECTION["min_sleep_window_min"]
    sleep_blocks = [
        p for p in periods if p["state"] == SLEEP and p["duration_min"] >= min_min
    ]
    if not sleep_blocks:
        return None, None
    return sleep_blocks[0]["start"], sleep_blocks[-1]["end"]


def hours_of_interrupted_sleep(periods: list[dict]) -> int:
    """Total hours of sleep (integer) counting all SLEEP blocks ≥ 5 min."""
    total = sum(
        p["duration_min"]
        for p in periods
        if p["state"] == SLEEP and p["duration_min"] >= 5
    )
    return int(total // 60)


def restlessness_minutes(df: pd.DataFrame) -> int:
    """
    Minutes of movement during sleep windows.
    Counts motion=True events and large distance spikes while is_sleep=True.
    """
    if df.empty or "is_sleep" not in df.columns:
        return 0

    sleep_mask = df["is_sleep"]
    restless_mask = pd.Series(False, index=df.index)

    if "motion" in df.columns:
        restless_mask |= (
            df["motion"].fillna(0).astype(int)
            >= SLEEP_DETECTION["motion_active_threshold"]
        )

    if "distance" in df.columns:
        dist_delta = df["distance"].diff().abs().fillna(0)
        restless_mask |= dist_delta > RESTLESSNESS["distance_spike_threshold"]

    during_sleep = restless_mask & sleep_mask
    sample_sec = SLEEP_DETECTION["sample_interval_secs"]
    return int((during_sleep.sum() * sample_sec) / 60)


def count_wake_events(periods: list[dict]) -> int:
    """Number of AWAKE interruptions ≥ 5 min during the main sleep window."""
    wake_min = SLEEP_DETECTION["wake_event_gap_min"]
    onset, wake_end = sleep_onset_and_wake(periods)
    if onset is None:
        return 0
    return sum(
        1
        for p in periods
        if p["state"] == AWAKE
        and p["duration_min"] >= wake_min
        and p["start"] >= onset
        and p["end"] <= wake_end
    )


def get_current_sleep_score(df: pd.DataFrame) -> float:
    """
    Return the latest smoothed sleep score from a DataFrame.
    Used by AlarmManager.tick() for smart wake decisions.
    Falls back to 0.5 if data is unavailable.
    """
    if df.empty or "sleep_score_smooth" not in df.columns:
        return 0.5
    val = df["sleep_score_smooth"].dropna()
    return float(val.iloc[-1]) if len(val) else 0.5
