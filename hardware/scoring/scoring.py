"""
hardware/scoring/scoring.py
Weighted sleep scoring model (6 components) and DB result writer.
Reads from the DataFrame produced by processing.py + detection.py,
writes results into sleep_sessions, sleep_scores, sleep_metric_scores.
"""

import sys
import os
import numpy as np
import pandas as pd
from datetime import datetime

_ALGOS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "algos"
)
if _ALGOS_DIR not in sys.path:
    sys.path.insert(0, _ALGOS_DIR)

_API_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "app", "backend", "api"
)
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

from config import (
    SCORE_WEIGHTS,
    SCORE_BANDS,
    SLEEP_DURATION,
    ENVIRONMENT,
    SLEEP_DETECTION,
)
from hardware.detection.detection import (
    extract_sleep_periods,
    sleep_onset_and_wake,
    hours_of_interrupted_sleep,
    restlessness_minutes,
    count_wake_events,
)


# ── Component scorers (each returns 0.0–1.0) ──────────────────────────────────


def score_sleep_duration(periods: list[dict]) -> float:
    """25% — total sleep hours vs ideal range."""
    total_hours = (
        sum(
            p["duration_min"]
            for p in periods
            if p["state"] == "SLEEP" and p["duration_min"] >= 5
        )
        / 60.0
    )

    ideal_min, ideal_max = SLEEP_DURATION["ideal_min"], SLEEP_DURATION["ideal_max"]
    acc_min, acc_max = (
        SLEEP_DURATION["acceptable_min"],
        SLEEP_DURATION["acceptable_max"],
    )

    if ideal_min <= total_hours <= ideal_max:
        return 1.0
    if total_hours < acc_min:
        return max(0.0, total_hours / acc_min)
    if total_hours > acc_max:
        return max(0.0, 1.0 - (total_hours - acc_max) / 2.0)
    if total_hours < ideal_min:
        return (total_hours - acc_min) / (ideal_min - acc_min) * 0.8 + 0.2
    return max(0.5, 1.0 - (total_hours - ideal_max) / (acc_max - ideal_max) * 0.5)


def score_sleep_efficiency(periods: list[dict]) -> float:
    """20% — sleep / time-in-bed minus fragmentation penalty."""
    onset, wake = sleep_onset_and_wake(periods)
    if onset is None:
        return 0.0
    time_in_bed = (wake - onset).total_seconds() / 60
    if time_in_bed < 1:
        return 0.0
    sleep_min = sum(
        p["duration_min"]
        for p in periods
        if p["state"] == "SLEEP" and p["duration_min"] >= 5
    )
    efficiency = min(sleep_min / time_in_bed, 1.0)
    n_wakes = count_wake_events(periods)
    return max(0.0, efficiency - n_wakes * 0.08)


def score_environmental(df: pd.DataFrame, periods: list[dict]) -> tuple[float, int]:
    """
    20% — temp, humidity, light, sound during sleep.
    Returns (raw_score 0–1, band 1/2/3).
    """
    sleep_df = df[df["is_sleep"]] if "is_sleep" in df.columns else df
    if sleep_df.empty:
        sleep_df = df

    component_scores = []

    for col, cfg_key in [("temperature", "temperature"), ("humidity", "humidity")]:
        if col in sleep_df.columns:
            vals = sleep_df[col].dropna()
            if len(vals):
                ideal = ENVIRONMENT[cfg_key]["ideal"]
                acc = ENVIRONMENT[cfg_key]["acceptable"]
                in_i = ((vals >= ideal[0]) & (vals <= ideal[1])).mean()
                in_a = ((vals >= acc[0]) & (vals <= acc[1])).mean()
                component_scores.append(in_i + (in_a - in_i) * 0.5)

    for col, cfg_key in [("light", "light"), ("sound", "sound")]:
        if col in sleep_df.columns:
            vals = sleep_df[col].dropna()
            if len(vals):
                ideal_max = ENVIRONMENT[cfg_key]["ideal_max"]
                acc_max = ENVIRONMENT[cfg_key]["acceptable_max"]
                in_i = (vals <= ideal_max).mean()
                in_a = (vals <= acc_max).mean()
                component_scores.append(in_i + (in_a - in_i) * 0.5)

    if not component_scores:
        return 0.5, 2

    raw = float(np.mean(component_scores))
    band = 3 if raw >= 0.70 else (2 if raw >= 0.40 else 1)
    return raw, band


def score_restfulness_index(df: pd.DataFrame) -> float:
    """20% (restfulness_index weight) — movement variance during sleep."""
    if "is_sleep" not in df.columns or df.empty:
        return 0.5

    sleep_df = df[df["is_sleep"]]
    if sleep_df.empty:
        return 0.5

    rates = []
    if "motion" in sleep_df.columns:
        rates.append(sleep_df["motion"].fillna(0).astype(int).mean())
    if "distance" in sleep_df.columns:
        avg_delta = sleep_df["distance"].diff().abs().dropna().mean()
        rates.append(min(avg_delta / 200.0, 1.0))

    if not rates:
        return 0.5
    return max(0.0, 1.0 - float(np.mean(rates)))


def score_breathing(df: pd.DataFrame) -> float:
    """10% — breathing regularity proxy using sound variance during sleep."""
    if "sound" not in df.columns or "is_sleep" not in df.columns:
        return 0.5
    sleep_sound = df[df["is_sleep"]]["sound"].dropna()
    if len(sleep_sound) < 5:
        return 0.5
    mean_std = sleep_sound.rolling(10, min_periods=3).std().dropna().mean()
    return float(1.0 - min(max((mean_std - 20) / 80, 0.0), 1.0))


def score_snoring_coughing(df: pd.DataFrame) -> float:
    """5% — fraction of sleep time above snore threshold."""
    if "sound" not in df.columns or "is_sleep" not in df.columns:
        return 0.8
    sleep_sound = df[df["is_sleep"]]["sound"].dropna()
    if len(sleep_sound) == 0:
        return 0.8
    snore_thr = SLEEP_DETECTION["sound_snore_threshold"]
    fraction = (sleep_sound > snore_thr).mean()
    if fraction <= 0.05:
        return 1.0
    if fraction >= 0.50:
        return 0.0
    return 1.0 - (fraction - 0.05) / 0.45


# ── Overall weighted score ─────────────────────────────────────────────────────


def compute_overall_score(df: pd.DataFrame, periods: list[dict]) -> dict:
    """
    Compute all 6 component scores and return the weighted composite.
    Returns full breakdown dict.
    """
    env_raw, env_band = score_environmental(df, periods)

    components = {
        "sleep_duration": score_sleep_duration(periods),
        "sleep_efficiency": score_sleep_efficiency(periods),
        "environmental": env_raw,
        "restfulness_index": score_restfulness_index(df),
        "breathing": score_breathing(df),
        "snoring_coughing": score_snoring_coughing(df),
    }

    weighted = sum(components[k] * SCORE_WEIGHTS[k] for k in components)
    weighted = round(min(max(weighted, 0.0), 1.0), 3)

    band = next(
        (b for b in SCORE_BANDS if b["min"] <= weighted <= b["max"]),
        SCORE_BANDS[-1],
    )

    return {
        "overall_score": weighted,
        "band": band["label"],
        "emoji": band["emoji"],
        "components": {k: round(v, 3) for k, v in components.items()},
        "env_band": env_band,
    }


# ── Full nightly report (in-memory, no DB) ─────────────────────────────────────


def nightly_report(df: pd.DataFrame) -> dict:
    """
    Master function: takes a cleaned + state-labelled DataFrame,
    returns all required output metrics.
    """
    from hardware.detection.detection import detect_sleep_states

    if "is_sleep" not in df.columns:
        df = detect_sleep_states(df)

    periods = extract_sleep_periods(df)
    onset, wake = sleep_onset_and_wake(periods)
    scores = compute_overall_score(df, periods)

    return {
        # ── Required outputs ───────────────────────────────────────────────
        "hours_of_interrupted_sleep": hours_of_interrupted_sleep(periods),  # int
        "restlessness_minutes": restlessness_minutes(df),  # int
        "environmental_score": scores["env_band"],  # 1/2/3
        "overall_score": scores["overall_score"],  # 0.0–1.0
        # ── Extra ──────────────────────────────────────────────────────────
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


# ── Consistency score (multi-night) ───────────────────────────────────────────


def consistency_score(nightly_onsets: list, nightly_wakes: list) -> float:
    """
    0.0–1.0 regularity of bed and wake times across multiple nights.
    Requires at least 3 nights.
    """
    from config import CONSISTENCY

    min_nights = CONSISTENCY["min_nights_required"]
    if len(nightly_onsets) < min_nights:
        return 0.5

    def mins_since_midnight(ts) -> float:
        t = ts.astimezone() if hasattr(ts, "astimezone") else ts
        return t.hour * 60 + t.minute + t.second / 60

    bed_mins = [mins_since_midnight(t) for t in nightly_onsets if t]
    wake_mins = [mins_since_midnight(t) for t in nightly_wakes if t]
    if not bed_mins:
        return 0.5

    bed_score = max(
        0.0, 1.0 - float(np.std(bed_mins)) / CONSISTENCY["set_bedtime_tolerance_min"]
    )
    wake_score = max(
        0.0, 1.0 - float(np.std(wake_mins)) / CONSISTENCY["waketime_tolerance_min"]
    )
    return round((bed_score + wake_score) / 2, 3)


# ── DB result writer ───────────────────────────────────────────────────────────


def save_session_to_db(
    flask_app, device_id: int, report: dict, algorithm_version: str = "1.0"
) -> int:
    """
    Persist a nightly_report() result into:
      sleep_sessions, sleep_scores, sleep_metric_scores

    Parameters
    ----------
    flask_app         : Flask app instance
    device_id         : int
    report            : dict from nightly_report()
    algorithm_version : str tag for audit trail

    Returns sleep_session_id (int)
    """
    from models import db, SleepSession, SleepScore, SleepMetricScore, SleepMetricType

    def _parse(s):
        if s is None:
            return None
        try:
            return datetime.fromisoformat(str(s)).replace(tzinfo=None)
        except Exception:
            return None

    onset = _parse(report.get("sleep_onset"))
    wake = _parse(report.get("wake_time"))
    periods = report.get("periods", [])
    total_sleep_min = sum(
        p["duration_min"]
        for p in periods
        if p.get("state") == "SLEEP" and p.get("duration_min", 0) >= 5
    )

    with flask_app.app_context():
        # sleep_sessions
        ss = SleepSession(
            device_id=device_id,
            start_time=onset,
            end_time=wake,
            total_sleep_minutes=int(total_sleep_min),
            sleep_efficiency=report["component_scores"].get("sleep_efficiency"),
            created_at=datetime.utcnow(),
        )
        db.session.add(ss)
        db.session.flush()
        session_id = ss.id

        # sleep_scores
        sc = SleepScore(
            sleep_session_id=session_id,
            algorithm_version=algorithm_version,
            total_score=report["overall_score"],
            calculated_at=datetime.utcnow(),
        )
        db.session.add(sc)
        db.session.flush()
        score_id = sc.id

        # sleep_metric_scores — one row per component
        metric_map = {mt.name: mt.id for mt in SleepMetricType.query.all()}

        raw_values = {
            "sleep_duration": report.get("hours_of_interrupted_sleep"),
            "sleep_efficiency": report["component_scores"].get("sleep_efficiency"),
            "environmental": report.get("environmental_score"),
            "restfulness_index": report.get("restlessness_minutes"),
            "breathing": None,
            "snoring_coughing": None,
        }

        for metric_name, comp_score in report["component_scores"].items():
            mt_id = metric_map.get(metric_name)
            if mt_id is None:
                # Auto-create metric type if missing
                mt = SleepMetricType(name=metric_name, description=metric_name)
                db.session.add(mt)
                db.session.flush()
                mt_id = mt.id

            db.session.add(
                SleepMetricScore(
                    sleep_score_id=score_id,
                    metric_type_id=mt_id,
                    score=comp_score,
                    raw_value=raw_values.get(metric_name),
                )
            )

        db.session.commit()

    print(
        f"[scoring] Session saved — id={session_id}  score={report['overall_score']:.3f}  "
        f"band={report['score_band']} {report['score_emoji']}"
    )
    return session_id


def get_label(score: float) -> str:
    band = next(
        (b for b in SCORE_BANDS if b["min"] <= score <= b["max"]), SCORE_BANDS[-1]
    )
    return f"{band['emoji']} {band['label']} ({score:.2f})"
