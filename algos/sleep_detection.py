import numpy as np
import pandas as pd
from config import SLEEP_DETECTION, RESTLESSNESS


# State Labels
AWAKE = "AWAKE"
SLEEP = "SLEEP"
UNCERTAIN = "UNCERTAIN"


# Row level sleep scoring
def _vote_light(val) -> float:
    """1.0 = definitely dark (asleep), 0.0 = bright (awake)."""
    if pd.isna(val):
        return 0.5  # abstain
    thr = SLEEP_DETECTION["light_sleep_threshold"]
    wake = SLEEP_DETECTION["light_wake_threshold"]
    if val <= thr:
        return 1.0
    if val >= wake:
        return 0.0
    return 1.0 - (val - thr) / (wake - thr)


def _vote_sound(val) -> float:
    """1.0 = quiet (asleep), 0.0 = loud (awake)."""
    if pd.isna(val):
        return 0.5
    thr = SLEEP_DETECTION["sound_sleep_threshold"]
    noise = SLEEP_DETECTION["sound_noise_event_threshold"]
    if val <= thr:
        return 1.0
    if val >= noise:
        return 0.0
    return 1.0 - (val - thr) / (noise - thr)


def _vote_motion(val) -> float:
    """1.0 = no motion (asleep), 0.0 = movement (awake)."""
    if pd.isna(val):
        return 0.5
    return 0.0 if val >= SLEEP_DETECTION["motion_active_threshold"] else 1.0


def _vote_distance(series: pd.Series, idx: int) -> float:
    """
    Compare current distance to rolling median of last 10 samples.
    Large delta → movement → awake.
    """
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


# Main sleep detect function


def detect_sleep_states(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds columns to df:
      sleep_score  — 0.0–1.0  (higher = more sleep-like)
      state        — SLEEP | AWAKE | UNCERTAIN
      is_sleep     — bool convenience flag
    Returns modified DataFrame.
    """
    df = df.copy()
    has_motion = "motion" in df.columns
    has_distance = "distance" in df.columns
    has_light = "light" in df.columns
    has_sound = "sound" in df.columns

    scores = []
    for i in range(len(df)):
        row = df.iloc[i]
        votes = []

        if has_light:
            votes.append((_vote_light(row["light"]), 2.0))  # weight
        if has_sound:
            votes.append((_vote_sound(row["sound"]), 2.0))
        if has_motion:
            votes.append((_vote_motion(row["motion"]), 3.0))  # strongest indicator
        if has_distance:
            votes.append((_vote_distance(df["distance"], i), 2.0))

        if not votes:
            scores.append(0.5)
            continue

        weighted_sum = sum(v * w for v, w in votes)
        total_weight = sum(w for _, w in votes)
        scores.append(weighted_sum / total_weight)

    df["sleep_score"] = scores

    # Apply minimum sleep window constraint via rolling smoothing
    window_samples = max(
        3,
        int(
            SLEEP_DETECTION["min_sleep_window_minutes"]
            * 60
            / SLEEP_DETECTION["sample_interval_seconds"]
            / 4
        ),  # 25% of window
    )
    df["sleep_score_smooth"] = (
        df["sleep_score"].rolling(window_samples, min_periods=1, center=True).mean()
    )

    def label(s):
        if s >= 0.65:
            return SLEEP
        if s <= 0.40:
            return AWAKE
        return UNCERTAIN

    df["state"] = df["sleep_score_smooth"].apply(label)
    df["is_sleep"] = df["state"] == SLEEP
    return df


# Nightly metrics based on detetected sleep states


def extract_sleep_periods(df: pd.DataFrame) -> list[dict]:
    """
    Return list of continuous sleep/wake blocks:
      {"state", "start", "end", "duration_min"}
    """
    if "state" not in df.columns:
        raise ValueError("Run detect_sleep_states() first.")

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

    # Final block
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
    """
    Returns (sleep_onset_ts, wake_ts) based on first sustained
    SLEEP block and last SLEEP block.
    """
    min_sleep_min = SLEEP_DETECTION["min_sleep_window_minutes"]
    sleep_blocks = [
        p for p in periods if p["state"] == SLEEP and p["duration_min"] >= min_sleep_min
    ]
    if not sleep_blocks:
        return None, None
    onset = sleep_blocks[0]["start"]
    wake = sleep_blocks[-1]["end"]
    return onset, wake


def hours_of_interrupted_sleep(periods: list[dict]) -> int:
    """
    Returns total hours of sleep (integer) as whole hours.
    Counts all SLEEP periods, including fragmented ones ≥ 5 min.
    """
    min_block = 5.0  # minutes
    total_min = sum(
        p["duration_min"]
        for p in periods
        if p["state"] == SLEEP and p["duration_min"] >= min_block
    )
    return int(total_min // 60)


def restlessness_minutes(df: pd.DataFrame, periods: list[dict]) -> int:
    """
    Restlessness = total minutes of movement during sleep windows.
    Counts motion events and distance spikes within SLEEP blocks.
    Returns integer (minutes).
    """
    has_motion = "motion" in df.columns
    has_distance = "distance" in df.columns

    sleep_mask = df["is_sleep"].copy()
    restless_mask = pd.Series(False, index=df.index)

    if has_motion:
        restless_mask |= df["motion"] >= SLEEP_DETECTION["motion_active_threshold"]

    if has_distance:
        dist_delta = df["distance"].diff().abs().fillna(0)
        restless_mask |= dist_delta > RESTLESSNESS["distance_spike_threshold"]

    # Only count restlessness during sleep periods
    during_sleep = restless_mask & sleep_mask

    # Calculate minutes: each sample represents sample_interval_seconds
    sample_sec = SLEEP_DETECTION["sample_interval_seconds"]
    restless_min = int((during_sleep.sum() * sample_sec) / 60)
    return restless_min


def count_wake_events(periods: list[dict]) -> int:
    """
    Number of times the person woke up (AWAKE blocks ≥ 5 min during main sleep).
    """
    wake_min = SLEEP_DETECTION["wake_event_gap_minutes"]
    onset, wake_end = sleep_onset_and_wake(periods)
    if onset is None:
        return 0
    interruptions = [
        p
        for p in periods
        if p["state"] == AWAKE
        and p["duration_min"] >= wake_min
        and p["start"] >= onset
        and p["end"] <= wake_end
    ]
    return len(interruptions)
