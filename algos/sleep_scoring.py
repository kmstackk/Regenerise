"""
Sleep scoring, weighted sleep algorithm
implements weighted model in IOT doc and calcs all the output ints
"""

import numpy as np
import pandas as pd
from datetime import timedelta

from pandas._libs.tslibs import periods_per_day
from config import (
    SCORE_WEIGHTS,
    SCORE_BANDS,
    SLEEP_DETECTION,
    SLEEP_DURATION,
    ENVIRONMENT,
    SLEEP_DETECTION,
    CONSISTENCY,
)
from sleep_detection import (
    extract_sleep_periods,
    sleep_onset_and_wake,
    hours_of_interrupted_sleep,
    restlessness_minutes,
    count_wake_events,
)


# Component Scorers (each returns a value between 0 and 1)
def score_sleep_duration(periods: list[dict]) -> float:
    # Total sleep hours vs ideal range
    min_block = 5.0
    total_min = sum(
        p["duration_min"]
        for p in periods
        if p["state"] == "SLEEP" and p["duration_min"] >= min_block
    )
    total_hours = total_min / 60.0
    ideal_min = SLEEP_DURATION["ideal_min"]
    ideal_max = SLEEP_DURATION["ideal_max"]
    acc_min = SLEEP_DURATION["acceptable_min"]
    acc_max = SLEEP_DURATION["acceptable_max"]

    if ideal_min <= total_hours <= ideal_max:
        return 1.0
    if total_hours < acc_min or total_hours > acc_max:
        # Outside acceptable → linear decay to 0
        if total_hours < acc_min:
            return max(0.0, total_hours / acc_min)
        else:
            excess = total_hours - acc_max
            return max(0.0, 1.0 - excess / 2.0)
    # Between acceptable and ideal → partial score
    if total_hours < ideal_min:
        return (total_hours - acc_min) / (ideal_min - acc_min) * 0.8 + 0.2
    else:
        deficit = total_hours - ideal_max
        return max(0.5, 1.0 - deficit / (acc_max - ideal_max) * 0.5)


def score_sleep_efficiency(periods: list[dict]) -> float:
    # Total sleep time / time in bed * continuity penalty (penalising if out of bed for long time)
    # Each extra wake up reduces overall score
    onset, wake_end = sleep_onset_and_wake(periods)
    if onset is None or wake_end is None:
        return 0.0

    time_in_bed_min = (wake_end - onset).total_seconds() / 60
    if time_in_bed_min < 1:
        return 0.0

    sleep_min = sum(
        p["duration_min"]
        for p in periods
        if p["state"] == "SLEEP" and p["duration_min"] >= 5
    )
    efficiency = sleep_min / time_in_bed_min
    efficiency = min(efficiency, 1.0)

    # Fragmentation penalty: each significant wake event → -0.08
    n_wakes = count_wake_events(periods)
    fragmentation_penalty = min(n_wakes * 0.08, 0.40)
    return max(0.0, efficiency - fragmentation_penalty)


def score_environmental(df: pd.DataFrame, periods: list[dict]) -> tuple[float, int]:
    # Evaluates if temp, humidity, light, sound during sleep windows
    # Will return normalised scored from 0 to 1 and also rate environment
    sleep_mask = df.get("is_sleep", pd.Series(True, index=df.index))
    sleep_df = df[sleep_mask]
    if len(sleep_df) == 0:
        sleep_df = df  # fallback to all data

    component_scores = []

    # Temperature
    if "temperature" in sleep_df.columns:
        temps = sleep_df["temperature"].dropna()
        if len(temps):
            ideal = ENVIRONMENT["temperature"]["ideal"]
            acc = ENVIRONMENT["temperature"]["acceptable"]
            in_ideal = ((temps >= ideal[0]) & (temps <= ideal[1])).mean()
            in_acc = ((temps >= acc[0]) & (temps <= acc[1])).mean()
            component_scores.append(in_ideal * 1.0 + (in_acc - in_ideal) * 0.5)

    # Humidity
    if "humidity" in sleep_df.columns:
        hums = sleep_df["humidity"].dropna()
        if len(hums):
            ideal = ENVIRONMENT["humidity"]["ideal"]
            acc = ENVIRONMENT["humidity"]["acceptable"]
            in_ideal = ((hums >= ideal[0]) & (hums <= ideal[1])).mean()
            in_acc = ((hums >= acc[0]) & (hums <= acc[1])).mean()
            component_scores.append(in_ideal * 1.0 + (in_acc - in_ideal) * 0.5)

    # Light
    if "light" in sleep_df.columns:
        lights = sleep_df["light"].dropna()
        if len(lights):
            ideal_max = ENVIRONMENT["light"]["ideal_max"]
            acc_max = ENVIRONMENT["light"]["acceptable_max"]
            in_ideal = (lights <= ideal_max).mean()
            in_acc = (lights <= acc_max).mean()
            component_scores.append(in_ideal * 1.0 + (in_acc - in_ideal) * 0.5)

    # Sound
    if "sound" in sleep_df.columns:
        sounds = sleep_df["sound"].dropna()
        if len(sounds):
            ideal_max = ENVIRONMENT["sound"]["ideal_max"]
            acc_max = ENVIRONMENT["sound"]["acceptable_max"]
            in_ideal = (sounds <= ideal_max).mean()
            in_acc = (sounds <= acc_max).mean()
            component_scores.append(in_ideal * 1.0 + (in_acc - in_ideal) * 0.5)

    if not component_scores:
        return 0.5, 2

    env_score = float(np.mean(component_scores))

    # Map to 1/2/3 band
    if env_score >= 0.70:
        env_band = 3
    elif env_score >= 0.40:
        env_band = 2
    else:
        env_band = 1

    return env_score, env_band


def score_breathing_stability(df: pd.DataFrame) -> float:
    # Checking breathing regularity and variance in sleep, low variance and low mean sound = stable breathing
    if "sound" not in df.columns or "is_sleep" not in df.columns:
        return 0.5  # abstain

    sleep_df = df[df["is_sleep"]]["sound"].dropna()
    if len(sleep_df) < 5:
        return 0.5

    rolling_std = sleep_df.rolling(10, min_periods=3).std().dropna()
    mean_std = rolling_std.mean()

    # Normalise: std < 20 → good, std > 100 → poor
    score = 1.0 - min(max((mean_std - 20) / 80, 0.0), 1.0)
    return float(score)


def score_restfulness_index(df: pd.DataFrame, periods: list[dict]) -> float:
    # Cheaching movement variance during sleep, lower = more rested
    has_motion = "motion" in df.columns
    has_distance = "distance" in df.columns

    if not (has_motion or has_distance):
        return 0.5

    sleep_mask = df.get("is_sleep", pd.Series(True, index=df.index))
    sleep_df = df[sleep_mask]

    if len(sleep_df) < 5:
        return 0.5

    movement_rates = []
    if has_motion:
        motion_rate = sleep_df["motion"].mean()
        movement_rates.append((motion_rate))

    if has_distance:
        dist_var = sleep_df["disance"].diff().abs().dropna().mean()
        dist_score = 1 - min(dist_var / 200, 1)  # 200 mm avg range = the worst
        movement_rates.append(1 - dist_score)

    avg_movement = float(np.mean(movement_rates))
    return max(0, 1 - avg_movement)


def score_snoring_coughing(df: pd.DataFrame) -> float:
    # noise events during sleeping that are above a certain threshold
    if "sound" not in df.columns or "is_sleep" not in df.columns:
        return 0.8

    sleep_df = df[df["is_sleep"]]["sound"].dropna()
    if len(sleep_df) == 0:
        return 0.8

    snore_thr = SLEEP_DETECTION["sound_snore_threshold"]
    snore_fraction = (sleep_df > snore_thr).mean()

    if snore_fraction <= 0.05:
        return 1
    if snore_fraction >= 0.5:
        return 0
    return 1 - (snore_fraction - 0.05) / 0.45


# Calculation of overall weighted score
def overall_score(df: pd.DataFrame, periods: list[dict]) -> dict:
    # Computes all of the components scores and returns a weighted overall score
    # returns full breakdown in dictionary
    env_score_raw, env_band = score_environmental(df, periods)

    components = {
        "sleep_duration": score_sleep_duration(periods),
        "sleep_efficiency": score_sleep_efficiency(periods),
        "environmental": env_score_raw,
        "physiological_stability": score_breathing_stability(df),
        "restfulness_index": score_restfulness_index(df, periods),
        "snoring_coughing": score_snoring_coughing(df),
    }

    weighted = sum(components[k] * SCORE_WEIGHTS[k] for k in components)
    weighted = round(min(max(weighted, 0), 1), 3)

    band = next(
        (b for b in SCORE_BANDS if b["min"] <= weighted <= b["max"]), SCORE_BANDS[-1]
    )
    return {
        "overall_score": weighted,
        "band": band["label"],
        "emoji": band["emoji"],
        "components": {k: round(v, 3) for k, v in components.items()},
        "weights": SCORE_WEIGHTS,
        "env_band": env_band,
    }


# Multi night consistency score
def consistency_score(nightly_onsets: list, nightly_wakes: list) -> float:
    # 0-1 consistency based on the regularity of sleep and waking times, pass lists of
    # datetime objects (once per night), requires >= CONSISTENCY["min_nights_required"] nights
    min_nights = CONSISTENCY["min_nights_required"]
    if len(nightly_onsets) < min_nights or len(nightly_wakes) < min_nights:
        return 0.5

    def time_of_day_min(ts) -> float:
    # convert timestamp of the mins since midnight
        t = ts.astimezone()
        return t.hour * 60 + t.minute + t.second / 60

    # sleep and wake times in min since midnight:
    sleep_min = [time_of_day_min(t) for t in nightly_onsets if t]
    wake_min = [time_of_day_min(t) for t in nightly_onsets if t]

    if not sleep_min or not wake_min:
        return 0.5
    
    sleep_std = float(np.std(sleep_min))
    wake_std = float(np.std(sleep_min))

    sleep_tol = CONSISTENCY["sleep_tolerance_min"]
    wake_tol = CONSISTENCY["wake_tolerance_min"]

    sleep_score = max(0, 1 - sleep_std / sleep_tol)
    wake_score = max(0, 1 - wake_std / wake_std)

    return round((sleep_score + wake_score) / 2, 3)


# Full nightly report
def nightly_report(df: pd.DataFrame) -> dict:
    # Master function: takes a clean & state-labelled dataframe, returns all required metrics
    from sleep_detection import detect_sleep_states

    if "is_sleep" not in df.columns:
        df = detect_sleep_states(df)

    periods = extract_sleep_periods(df)
    onset, wake = sleep_onset_and_wake(periods)
    scores = overall_score(df, periods)

    report = {
        # Required output ints and floats
        "hours_of_interrupted_sleep": hours_of_interrupted_sleep(periods),  # int
        "restlessness_minutes": restlessness_minutes(df, periods),  # int
        "environmental_score": scores["env_band"],  # 1/2/3
        "overall_score": scores["overall_score"],  # 0.0–1.0
        # consistency_score computed separately (needs multi-night data)
        # additional useful info
        "sleep_onset": onset.isoformat() if onset else None,
        "wake_time": wake.isoformat() if wake else None,
        "total_wake_events": count_wake_events(periods),
        "score_band": scores["band"],
        "score_emoji": scores["emoji"],
        "component_scores": scores["components"],
        "periods": [
            {**p, "start": p["start"].isoformat(), "end": p["end"].isoformat()}
            for p in periods
        ],
    }
    return report


def get_score_label(score: float) -> str:
    band = next(
        (b for b in SCORE_BANDS if b["min"] <= score <= b["max"]), SCORE_BANDS[-1]
    )
    return f"{band['emoji']} {band['label']} ({score:.2f})"
