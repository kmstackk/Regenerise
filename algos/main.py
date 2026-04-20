"""
main.py — Sleep Tracker Entry Point
Runs the full pipeline on CSV data and prints a nightly report.
Also demonstrates multi-night consistency scoring.
"""

import json
from datetime import datetime
import pandas as pd

from data_processing import load_csv, summary_stats
from sleep_detection import detect_sleep_states
from sleep_scoring import nightly_report, consistency_score, get_score_label
from alarm import AlarmManager, Alarm


# Pipeline


def run_pipeline(csv_path: str, label: str = "Night") -> dict:
    print(f"\n{'━' * 55}")
    print(f"  Processing: {label}  ({csv_path})")
    print(f"{'━' * 55}")

    # 1. Load & clean
    df = load_csv(csv_path)
    stats = summary_stats(df)
    print(
        f"  Loaded {stats['n_rows']} rows  |  "
        f"Duration: {stats['duration_min']:.0f} min  |  "
        f"Sensors: {[c for c in stats['columns'] if c != 'timestamp']}"
    )

    # 2. Detect sleep states
    df = detect_sleep_states(df)
    sleep_pct = df["is_sleep"].mean() * 100
    print(f"  Sleep detected: {sleep_pct:.1f}% of session")

    # 3. Score
    report = nightly_report(df)

    # ── Print human-readable summary ────────────────────────────────────────
    print(f"\n  ┌─ NIGHTLY REPORT: {label} ─────────────────────────────")
    print(f"  │  Overall Score  : {get_score_label(report['overall_score'])}")
    print(f"  │  Sleep (hours)  : {report['hours_of_interrupted_sleep']}h")
    print(f"  │  Restlessness   : {report['restlessness_minutes']} min")
    print(f"  │  Env Score      : {report['environmental_score']} / 3")
    print(f"  │  Wake Events    : {report['total_wake_events']}")
    print(f"  │  Sleep Onset    : {report['sleep_onset'] or 'N/A'}")
    print(f"  │  Wake Time      : {report['wake_time'] or 'N/A'}")
    print(f"  │")
    print(f"  │  Component Scores:")
    for k, v in report["component_scores"].items():
        bar = "█" * int(v * 20) + "░" * (20 - int(v * 20))
        print(f"  │    {k:<28} {bar}  {v:.2f}")
    print(f"  └────────────────────────────────────────────────────")

    return report


def demo_consistency(reports: list[dict]) -> None:
    """Demo consistency scoring across multiple nights."""
    onsets = []
    wakes = []
    for r in reports:
        if r["sleep_onset"]:
            onsets.append(datetime.fromisoformat(r["sleep_onset"]))
        if r["wake_time"]:
            wakes.append(datetime.fromisoformat(r["wake_time"]))

    if len(onsets) >= 2:
        score = consistency_score(onsets, wakes)
        print(f"\n  ┌─ CONSISTENCY SCORE ────────────────────────────────")
        print(f"  │  Based on {len(onsets)} nights")
        print(f"  │  Score: {get_score_label(score)}")
        print(f"  └────────────────────────────────────────────────────")


def demo_alarm() -> None:
    """Show alarm configuration."""
    print(f"\n  ┌─ ALARM CONFIGURATION ──────────────────────────────")
    manager = AlarmManager()
    manager.add_alarm(
        Alarm(
            hour=7,
            minute=0,
            days_of_week=[0, 1, 2, 3, 4],
            label="Weekday wake",
            smart_wake=True,
            snooze_duration=9,
            max_snoozes=3,
        )
    )
    manager.add_alarm(
        Alarm(
            hour=9,
            minute=0,
            days_of_week=[5, 6],
            label="Weekend lie-in",
            smart_wake=False,
            snooze_duration=15,
            max_snoozes=2,
        )
    )
    manager.list_alarms()
    print(f"  └────────────────────────────────────────────────────")


# Main

if __name__ == "__main__":
    reports = []

    r1 = run_pipeline("data_overnight.csv", "Night 1 (overnight)")
    reports.append(r1)

    r2 = run_pipeline("more_test_data.csv", "Night 2 (short session)")
    reports.append(r2)

    demo_consistency(reports)
    demo_alarm()

    print("\n  ✅  Pipeline complete.\n")
