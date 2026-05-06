import sys
import time
import argparse
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

CSV_FILE = "full_overnight_data.csv"

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — CONFIG  (mirrors algos/config.py)
# ─────────────────────────────────────────────────────────────────────────────

SCORE_WEIGHTS = {
    "sleep_duration": 0.25,
    "sleep_efficiency": 0.20,
    "environmental": 0.20,
    "restfulness_index": 0.20,
    "breathing": 0.10,
    "snoring_coughing": 0.05,
}

SCORE_BANDS = [
    {"min": 0.85, "max": 1.00, "label": "Excellent", "emoji": "🌟"},
    {"min": 0.70, "max": 0.85, "label": "Good", "emoji": "✅"},
    {"min": 0.55, "max": 0.70, "label": "Fair", "emoji": "⚠️"},
    {"min": 0.40, "max": 0.55, "label": "Poor", "emoji": "😴"},
    {"min": 0.00, "max": 0.40, "label": "Very Poor", "emoji": "❌"},
]

SLEEP_DETECTION = {
    "light_sleep_threshold": 50,
    "light_awake_threshold": 150,
    "sound_sleep_threshold": 120,
    "sound_change_occur_threshold": 300,
    "sound_snore_threshold": 200,
    "motion_active_threshold": 1,
    "distance_change_threshold": 50,
    "min_sleep_window_min": 30,
    "wake_event_gap_min": 5,
    "sample_interval_secs": 10,
}

ENVIRONMENT = {
    "temperature": {"ideal": (16.0, 19.0), "acceptable": (14.0, 22.0)},
    "humidity": {"ideal": (40.0, 60.0), "acceptable": (30.0, 70.0)},
    "light": {"ideal_max": 30, "acceptable_max": 80},
    "sound": {"ideal_max": 120, "acceptable_max": 200},
}

SLEEP_DURATION = {
    "ideal_min": 7.0,
    "ideal_max": 9.0,
    "acceptable_min": 6.0,
    "acceptable_max": 10.0,
}

ALARM_DEFAULTS = {
    "snooze_duration_minutes": 9,
    "max_snoozes": 3,
    "smart_alarm_window": 20,
    "vibration_pattern": [500, 200, 500, 200, 1000],
    "days_of_week": [],
}


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — DATA PROCESSING  (mirrors hardware/processing/processing.py)
# ─────────────────────────────────────────────────────────────────────────────


def load_csv(path: str) -> pd.DataFrame:
    """
    Load sensor CSV and clean it.
    In production this is replaced by load_from_db() which queries
    the SensorData table — the returned DataFrame is identical.
    """
    df = pd.read_csv(path)

    # Parse epoch-ms timestamps → UTC datetime
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

    # Clamp motion to 0/1 (values of 2 are sensor glitches)
    if "motion" in df.columns:
        df.loc[df["motion"] > 1, "motion"] = 0

    # Validate ranges — out-of-range → NaN
    ranges = {
        "temperature": (-10.0, 50.0),
        "humidity": (0.0, 100.0),
        "light": (0, 1023),
        "sound": (0, 1023),
        "distance": (0, 5000),
    }
    for col, (lo, hi) in ranges.items():
        if col in df.columns:
            bad = (df[col] < lo) | (df[col] > hi)
            if bad.sum():
                print(f"  [processing] {col}: {bad.sum()} out-of-range values → NaN")
            df.loc[bad, col] = np.nan

    # Fill short gaps (≤5 samples) then smooth ADC noise
    sensor_cols = [c for c in ranges if c in df.columns]
    df[sensor_cols] = df[sensor_cols].ffill(limit=5).bfill(limit=5)
    for col in ["temperature", "humidity", "light", "sound", "distance"]:
        if col in df.columns:
            df[col] = df[col].rolling(3, min_periods=1, center=True).median()

    return df.sort_values("timestamp").reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — SLEEP DETECTION  (mirrors hardware/detection/detection.py)
# ─────────────────────────────────────────────────────────────────────────────


def detect_sleep_states(df: pd.DataFrame) -> pd.DataFrame:
    """
    Per-row weighted voting state machine.
    Each sensor casts a vote (0=awake, 1=asleep) weighted by reliability:
      motion=3, light=2, sound=2, distance=2
    Votes are averaged, smoothed over a rolling window, then thresholded
    into SLEEP / AWAKE / UNCERTAIN labels.
    """
    df = df.copy()

    def vote_light(v):
        if pd.isna(v):
            return 0.5
        thr, wake = (
            SLEEP_DETECTION["light_sleep_threshold"],
            SLEEP_DETECTION["light_awake_threshold"],
        )
        return (
            1.0 if v <= thr else (0.0 if v >= wake else 1.0 - (v - thr) / (wake - thr))
        )

    def vote_sound(v):
        if pd.isna(v):
            return 0.5
        thr, noise = (
            SLEEP_DETECTION["sound_sleep_threshold"],
            SLEEP_DETECTION["sound_change_occur_threshold"],
        )
        return (
            1.0
            if v <= thr
            else (0.0 if v >= noise else 1.0 - (v - thr) / (noise - thr))
        )

    def vote_motion(v):
        if pd.isna(v):
            return 0.5
        return 0.0 if int(v) >= SLEEP_DETECTION["motion_active_threshold"] else 1.0

    def vote_distance(series, idx):
        if pd.isna(series.iloc[idx]):
            return 0.5
        ref = series.iloc[max(0, idx - 10) : idx].median()
        if pd.isna(ref):
            return 0.5
        delta = abs(series.iloc[idx] - ref)
        thr = SLEEP_DETECTION["distance_change_threshold"]
        return (
            1.0
            if delta <= thr
            else (0.0 if delta >= thr * 3 else 1.0 - (delta - thr) / (thr * 2))
        )

    has = {c: c in df.columns for c in ["light", "sound", "motion", "distance"]}
    scores = []
    for i in range(len(df)):
        row, votes = df.iloc[i], []
        if has["light"]:
            votes.append((vote_light(row["light"]), 2.0))
        if has["sound"]:
            votes.append((vote_sound(row["sound"]), 2.0))
        if has["motion"]:
            votes.append((vote_motion(row["motion"]), 3.0))
        if has["distance"]:
            votes.append((vote_distance(df["distance"], i), 2.0))
        scores.append(
            sum(v * w for v, w in votes) / sum(w for _, w in votes) if votes else 0.5
        )

    df["sleep_score"] = scores
    window = max(
        3,
        int(
            SLEEP_DETECTION["min_sleep_window_min"]
            * 60
            / SLEEP_DETECTION["sample_interval_secs"]
            / 4
        ),
    )
    df["sleep_score_smooth"] = (
        df["sleep_score"].rolling(window, min_periods=1, center=True).mean()
    )

    def label(s):
        return "SLEEP" if s >= 0.65 else ("AWAKE" if s <= 0.40 else "UNCERTAIN")

    df["state"] = df["sleep_score_smooth"].apply(label)
    df["is_sleep"] = df["state"] == "SLEEP"
    return df


def extract_periods(df):
    periods, cur, start = [], df["state"].iloc[0], df["timestamp"].iloc[0]
    for i in range(1, len(df)):
        s = df["state"].iloc[i]
        if s != cur:
            end = df["timestamp"].iloc[i]
            periods.append(
                {
                    "state": cur,
                    "start": start,
                    "end": end,
                    "duration_min": round((end - start).total_seconds() / 60, 1),
                }
            )
            cur, start = s, end
    end = df["timestamp"].iloc[-1]
    periods.append(
        {
            "state": cur,
            "start": start,
            "end": end,
            "duration_min": round((end - start).total_seconds() / 60, 1),
        }
    )
    return periods


def sleep_onset_wake(periods):
    min_m = SLEEP_DETECTION["min_sleep_window_min"]
    blocks = [
        p for p in periods if p["state"] == "SLEEP" and p["duration_min"] >= min_m
    ]
    return (blocks[0]["start"], blocks[-1]["end"]) if blocks else (None, None)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — SCORING  (mirrors hardware/scoring/scoring.py)
# ─────────────────────────────────────────────────────────────────────────────


def score_sleep_duration(periods):
    total_h = (
        sum(
            p["duration_min"]
            for p in periods
            if p["state"] == "SLEEP" and p["duration_min"] >= 5
        )
        / 60
    )
    lo, hi = SLEEP_DURATION["ideal_min"], SLEEP_DURATION["ideal_max"]
    alo, ahi = SLEEP_DURATION["acceptable_min"], SLEEP_DURATION["acceptable_max"]
    if lo <= total_h <= hi:
        return 1.0
    if total_h < alo:
        return max(0.0, total_h / alo)
    if total_h > ahi:
        return max(0.0, 1.0 - (total_h - ahi) / 2.0)
    if total_h < lo:
        return (total_h - alo) / (lo - alo) * 0.8 + 0.2
    return max(0.5, 1.0 - (total_h - hi) / (ahi - hi) * 0.5)


def score_sleep_efficiency(periods):
    onset, wake = sleep_onset_wake(periods)
    if onset is None:
        return 0.0
    tib = (wake - onset).total_seconds() / 60
    slept = sum(
        p["duration_min"]
        for p in periods
        if p["state"] == "SLEEP" and p["duration_min"] >= 5
    )
    n_wakes = sum(
        1
        for p in periods
        if p["state"] == "AWAKE"
        and p["duration_min"] >= SLEEP_DETECTION["wake_event_gap_min"]
        and onset <= p["start"] <= wake
    )
    return max(0.0, min(slept / tib, 1.0) - n_wakes * 0.08)


def score_environmental(df, periods):
    sd = df[df["is_sleep"]] if "is_sleep" in df.columns else df
    if sd.empty:
        sd = df
    parts = []
    for col, key in [("temperature", "temperature"), ("humidity", "humidity")]:
        if col in sd.columns:
            v = sd[col].dropna()
            if len(v):
                i = ENVIRONMENT[key]["ideal"]
                a = ENVIRONMENT[key]["acceptable"]
                parts.append(
                    ((v >= i[0]) & (v <= i[1])).mean()
                    + (
                        ((v >= a[0]) & (v <= a[1])).mean()
                        - ((v >= i[0]) & (v <= i[1])).mean()
                    )
                    * 0.5
                )
    for col, key in [("light", "light"), ("sound", "sound")]:
        if col in sd.columns:
            v = sd[col].dropna()
            if len(v):
                im = ENVIRONMENT[key]["ideal_max"]
                am = ENVIRONMENT[key]["acceptable_max"]
                parts.append(
                    (v <= im).mean() + ((v <= am).mean() - (v <= im).mean()) * 0.5
                )
    if not parts:
        return 0.5, 2
    raw = float(np.mean(parts))
    band = 3 if raw >= 0.70 else (2 if raw >= 0.40 else 1)
    return raw, band


def score_restfulness(df):
    if "is_sleep" not in df.columns or df.empty:
        return 0.5
    sd = df[df["is_sleep"]]
    rates = []
    if "motion" in sd.columns:
        rates.append(sd["motion"].fillna(0).astype(int).mean())
    if "distance" in sd.columns:
        rates.append(min(sd["distance"].diff().abs().dropna().mean() / 200.0, 1.0))
    return max(0.0, 1.0 - float(np.mean(rates))) if rates else 0.5


def score_breathing(df):
    if "sound" not in df.columns or "is_sleep" not in df.columns:
        return 0.5
    ss = df[df["is_sleep"]]["sound"].dropna()
    if len(ss) < 5:
        return 0.5
    return float(
        1.0
        - min(
            max((ss.rolling(10, min_periods=3).std().dropna().mean() - 20) / 80, 0.0),
            1.0,
        )
    )


def score_snoring(df):
    if "sound" not in df.columns or "is_sleep" not in df.columns:
        return 0.8
    ss = df[df["is_sleep"]]["sound"].dropna()
    if len(ss) == 0:
        return 0.8
    f = (ss > SLEEP_DETECTION["sound_snore_threshold"]).mean()
    return 1.0 if f <= 0.05 else (0.0 if f >= 0.50 else 1.0 - (f - 0.05) / 0.45)


def compute_score(df, periods):
    env_raw, env_band = score_environmental(df, periods)
    components = {
        "sleep_duration": score_sleep_duration(periods),
        "sleep_efficiency": score_sleep_efficiency(periods),
        "environmental": env_raw,
        "restfulness_index": score_restfulness(df),
        "breathing": score_breathing(df),
        "snoring_coughing": score_snoring(df),
    }
    weighted = round(
        min(max(sum(components[k] * SCORE_WEIGHTS[k] for k in components), 0.0), 1.0), 3
    )
    band = next(
        (b for b in SCORE_BANDS if b["min"] <= weighted <= b["max"]), SCORE_BANDS[-1]
    )
    return weighted, band, components, env_band


def hours_of_sleep(periods):
    return int(
        sum(
            p["duration_min"]
            for p in periods
            if p["state"] == "SLEEP" and p["duration_min"] >= 5
        )
        // 60
    )


def restlessness_min(df):
    if df.empty or "is_sleep" not in df.columns:
        return 0
    sm = df["is_sleep"]
    rm = pd.Series(False, index=df.index)
    if "motion" in df.columns:
        rm |= df["motion"].fillna(0).astype(int) >= 1
    if "distance" in df.columns:
        rm |= df["distance"].diff().abs().fillna(0) > 100
    return int(((rm & sm).sum() * SLEEP_DETECTION["sample_interval_secs"]) / 60)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — ALARM  (mirrors algos/alarm.py)
# ─────────────────────────────────────────────────────────────────────────────


def demo_alarm():
    """Fire an alarm in 5 seconds to show the buzzer logic live."""
    import threading

    fire_at = datetime.now() + timedelta(seconds=5)
    print(f"\n  [alarm] Alarm set for {fire_at:%H:%M:%S}  (5 seconds from now)")
    print(
        f"  [alarm] Smart wake window: {ALARM_DEFAULTS['smart_alarm_window']} min before alarm"
    )
    print(
        f"  [alarm] Snooze duration  : {ALARM_DEFAULTS['snooze_duration_minutes']} min"
    )
    print(f"  [alarm] Max snoozes      : {ALARM_DEFAULTS['max_snoozes']}")

    time.sleep(5)

    print(f"\n{'=' * 45}")
    print(f"  ⏰  Morning Alarm  —  {datetime.now():%H:%M:%S}")
    print(f"{'=' * 45}")

    pattern = ALARM_DEFAULTS["vibration_pattern"]
    print(f"  [buzzer] Pattern: {pattern} ms  (on/off/on/off/on)")
    for i, duration in enumerate(pattern):
        if i % 2 == 0:
            print(f"  [BUZZER ON]  freq=1000Hz  for {duration}ms")
        else:
            print(f"  [BUZZER OFF]              for {duration}ms")
        time.sleep(duration / 1000)
    print(f"  [BUZZER OFF]")
    print(f"\n  → In production: RPi.GPIO.output(BUZZER_PIN, HIGH/LOW)")
    print(f"  → Snooze/dismiss wired to physical GPIO buttons")

    print(f"\n  Simulating snooze press …")
    time.sleep(1)
    print(
        f"  [alarm] Snooze #1 — re-fires in {ALARM_DEFAULTS['snooze_duration_minutes']} min"
    )
    print(f"  [alarm] (demo stops here — real system would re-fire)")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6 — DATABASE WRITE  (mirrors hardware/scoring/scoring.py)
# ─────────────────────────────────────────────────────────────────────────────


def demo_db_write(report: dict):
    """Write results to a local SQLite DB to show the DB pipeline working."""
    import sqlite3, os

    db_path = "demo_sleep.db"
    print(f"\n  [db] Writing results to {db_path} …")

    con = sqlite3.connect(db_path)
    cur = con.cursor()

    # Create tables (mirrors the real schema)
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS sleep_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id INTEGER, start_time TEXT, end_time TEXT,
            total_sleep_minutes INTEGER, sleep_efficiency REAL, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS sleep_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sleep_session_id INTEGER, algorithm_version TEXT,
            total_score REAL, calculated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS sleep_metric_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sleep_score_id INTEGER, metric_name TEXT,
            score REAL, raw_value REAL
        );
    """)

    # Insert sleep session
    cur.execute(
        """
        INSERT INTO sleep_sessions (device_id, start_time, end_time,
            total_sleep_minutes, sleep_efficiency, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (
            1,
            report["sleep_onset"],
            report["wake_time"],
            report["hours_of_interrupted_sleep"] * 60,
            report["components"]["sleep_efficiency"],
            datetime.utcnow().isoformat(),
        ),
    )
    session_id = cur.lastrowid

    # Insert overall score
    cur.execute(
        """
        INSERT INTO sleep_scores (sleep_session_id, algorithm_version, total_score, calculated_at)
        VALUES (?, ?, ?, ?)
    """,
        (session_id, "1.0", report["overall_score"], datetime.utcnow().isoformat()),
    )
    score_id = cur.lastrowid

    # Insert component scores
    raw_vals = {
        "sleep_duration": report["hours_of_interrupted_sleep"],
        "sleep_efficiency": None,
        "environmental": report["environmental_score"],
        "restfulness_index": report["restlessness_minutes"],
        "breathing": None,
        "snoring_coughing": None,
    }
    for name, score in report["components"].items():
        cur.execute(
            """
            INSERT INTO sleep_metric_scores (sleep_score_id, metric_name, score, raw_value)
            VALUES (?, ?, ?, ?)
        """,
            (score_id, name, score, raw_vals.get(name)),
        )

    con.commit()

    # Read it back to show it worked
    print(f"  [db] Written. Reading back from DB to verify:\n")
    row = cur.execute(
        """
        SELECT ss.id, ss.start_time, ss.end_time, ss.total_sleep_minutes,
               sc.total_score, sc.algorithm_version
        FROM sleep_sessions ss
        JOIN sleep_scores sc ON sc.sleep_session_id = ss.id
        WHERE ss.id = ?
    """,
        (session_id,),
    ).fetchone()

    print(f"  ┌─ sleep_sessions + sleep_scores ─────────────────────")
    print(f"  │  session_id       : {row[0]}")
    print(f"  │  start_time       : {row[1]}")
    print(f"  │  end_time         : {row[2]}")
    print(f"  │  total_sleep_min  : {row[3]}")
    print(f"  │  total_score      : {row[4]}")
    print(f"  │  algorithm_version: {row[5]}")
    print(f"  └─────────────────────────────────────────────────────")

    metrics = cur.execute(
        """
        SELECT metric_name, score, raw_value FROM sleep_metric_scores
        WHERE sleep_score_id = ?
    """,
        (score_id,),
    ).fetchall()

    print(f"\n  ┌─ sleep_metric_scores ────────────────────────────────")
    for m in metrics:
        raw = f"  (raw={m[2]})" if m[2] is not None else ""
        print(f"  │  {m[0]:<22} score={m[1]:.3f}{raw}")
    print(f"  └─────────────────────────────────────────────────────")

    con.close()
    print(f"\n  [db] Verified — all data round-trips correctly.")
    print(f"  [db] In production: Flask app serves this via GET /api/sleep/latest")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--alarm", action="store_true", help="Demo alarm firing")
    parser.add_argument(
        "--db", action="store_true", help="Write results to demo SQLite DB"
    )
    args = parser.parse_args()

    print(f"\n{'━' * 55}")
    print(f"  Sleep Tracker — Algorithm Demo")
    print(f"  {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"{'━' * 55}")

    # ── Step 1: Load & process data ───────────────────────────────────────────
    print(f"\n── STEP 1: DATA PROCESSING ──────────────────────────────")
    print(f"  Source  : {CSV_FILE}")
    print(f"  (In production this is replaced by load_from_db()")
    print(f"   querying the SensorData table — identical output)\n")

    df = load_csv(CSV_FILE)
    duration_h = (df["timestamp"].max() - df["timestamp"].min()).total_seconds() / 3600
    print(f"  Loaded  : {len(df)} rows  |  {duration_h:.1f} hours of data")
    print(f"  Sensors : {[c for c in df.columns if c != 'timestamp']}")
    print(f"  Sample  :")
    print(
        df[["timestamp", "temperature", "humidity", "light", "sound", "motion"]]
        .head(3)
        .to_string(index=False)
    )

    # ── Step 2: Sleep detection ───────────────────────────────────────────────
    print(f"\n── STEP 2: SLEEP DETECTION ──────────────────────────────")
    print(f"  Weighted sensor voting per sample:")
    print(f"    motion=3  light=2  sound=2  distance=2")
    print(f"  Rolling smooth → threshold → SLEEP / AWAKE / UNCERTAIN\n")

    df = detect_sleep_states(df)
    periods = extract_periods(df)
    onset, wake = sleep_onset_wake(periods)

    sleep_pct = df["is_sleep"].mean() * 100
    print(f"  Sleep detected  : {sleep_pct:.1f}% of session")
    print(f"  Sleep onset     : {onset.strftime('%H:%M') if onset else 'N/A'}")
    print(f"  Wake time       : {wake.strftime('%H:%M') if wake else 'N/A'}")
    print(f"\n  State blocks (first 8):")
    print(f"  {'State':<12} {'Start':>8} {'End':>8} {'Mins':>7}")
    print(f"  {'─' * 40}")
    for p in periods[:8]:
        print(
            f"  {p['state']:<12} {p['start'].strftime('%H:%M'):>8} "
            f"{p['end'].strftime('%H:%M'):>8} {p['duration_min']:>7.1f}"
        )
    if len(periods) > 8:
        print(f"  ... ({len(periods) - 8} more blocks)")

    # ── Step 3: Scoring ───────────────────────────────────────────────────────
    print(f"\n── STEP 3: SLEEP SCORING ────────────────────────────────")
    print(f"  Applying weighted model:")
    for k, w in SCORE_WEIGHTS.items():
        print(f"    {k:<22} weight={w:.0%}")

    overall, band, components, env_band = compute_score(df, periods)
    hrs = hours_of_sleep(periods)
    rest = restlessness_min(df)

    print(f"\n  ┌─ REQUIRED OUTPUTS ──────────────────────────────────")
    print(f"  │  hours_of_interrupted_sleep : {hrs}h")
    print(f"  │  restlessness_minutes       : {rest} min")
    print(f"  │  environmental_score        : {env_band} / 3")
    print(
        f"  │  overall_score              : {overall}  {band['emoji']} {band['label']}"
    )
    print(f"  └─────────────────────────────────────────────────────")

    print(f"\n  Component breakdown:")
    for k, v in components.items():
        w = SCORE_WEIGHTS[k]
        bar = "█" * int(v * 20) + "░" * (20 - int(v * 20))
        print(f"  {k:<22} {bar}  {v:.2f}  (×{w:.0%})")

    report = {
        "overall_score": overall,
        "hours_of_interrupted_sleep": hrs,
        "restlessness_minutes": rest,
        "environmental_score": env_band,
        "sleep_onset": onset.isoformat() if onset else None,
        "wake_time": wake.isoformat() if wake else None,
        "components": components,
        "score_band": band["label"],
        "score_emoji": band["emoji"],
    }

    # ── Step 4 (optional): Alarm demo ─────────────────────────────────────────
    if args.alarm:
        print(f"\n── STEP 4: ALARM DEMO ───────────────────────────────────")
        demo_alarm()

    # ── Step 5 (optional): DB write ───────────────────────────────────────────
    if args.db:
        print(f"\n── STEP 5: DATABASE WRITE ───────────────────────────────")
        demo_db_write(report)

    print(f"\n{'━' * 55}")
    print(f"  Demo complete.")
    print(f"{'━' * 55}\n")


if __name__ == "__main__":
    main()
