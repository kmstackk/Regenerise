import sys
import os
import time
from datetime import datetime, timedelta

# ── Path setup ─────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.join(_HERE, "..")

for _p in [
    _ROOT,
    os.path.join(_ROOT, "algos"),
    os.path.join(_ROOT, "app", "backend", "api"),
    os.path.join(_ROOT, "hardware"),
]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── Flask app (shared DB context) ─────────────────────────────────────────────
from app import app as flask_app  # app/backend/api/app.py

# ── Hardware modules ───────────────────────────────────────────────────────────
from hardware.processing.processing import load_from_db, summary
from hardware.detection.detection import detect_sleep_states, get_current_sleep_score
from hardware.scoring.scoring import nightly_report, save_session_to_db, get_label

# ── Alarm manager (from algos, uses Flask DB) ──────────────────────────────────
from alarm import AlarmManager, Alarm


# ── Config ────────────────────────────────────────────────────────────────────
DEVICE_ID = 1  # Change to match your device row in the devices table
TICK_INTERVAL_S = 30  # seconds between alarm checks
SCORE_INTERVAL_H = 1  # hours between scoring runs
LOAD_WINDOW_H = 12  # hours of sensor data to load for scoring


# ── Helpers ────────────────────────────────────────────────────────────────────


def _print_report(report: dict) -> None:
    print(f"\n  ┌─ NIGHTLY REPORT ────────────────────────────────────")
    print(f"  │  Score          : {get_label(report['overall_score'])}")
    print(f"  │  Sleep (hours)  : {report['hours_of_interrupted_sleep']}h")
    print(f"  │  Restlessness   : {report['restlessness_minutes']} min")
    print(f"  │  Env Score      : {report['environmental_score']} / 3")
    print(f"  │  Wake Events    : {report['total_wake_events']}")
    print(f"  │  Sleep Onset    : {report['sleep_onset'] or 'N/A'}")
    print(f"  │  Wake Time      : {report['wake_time'] or 'N/A'}")
    print(f"  │  Components:")
    for k, v in report["component_scores"].items():
        bar = "█" * int(v * 20) + "░" * (20 - int(v * 20))
        print(f"  │    {k:<22} {bar}  {v:.2f}")
    print(f"  └─────────────────────────────────────────────────────\n")


def run_scoring_pipeline() -> None:
    """Load latest DB data → detect → score → save to DB."""
    print(f"\n[main] Running scoring pipeline at {datetime.now():%H:%M:%S}")
    df = load_from_db(flask_app, DEVICE_ID, hours_back=LOAD_WINDOW_H)

    if df.empty:
        print("[main] No sensor data found — skipping scoring.")
        return

    info = summary(df)
    print(f"[main] Loaded {info['n_rows']} rows  |  {info['duration_min']:.0f} min")

    df = detect_sleep_states(df)
    sleep_p = df["is_sleep"].mean() * 100
    print(f"[main] Sleep detected in {sleep_p:.1f}% of session")

    report = nightly_report(df)
    _print_report(report)
    save_session_to_db(flask_app, DEVICE_ID, report)


# ── Main loop ──────────────────────────────────────────────────────────────────


def main() -> None:
    print(f"\n{'━' * 55}")
    print(f"  Sleep Tracker — Pi Main Loop")
    print(f"  Device ID : {DEVICE_ID}")
    print(f"  DB        : {flask_app.config['SQLALCHEMY_DATABASE_URI']}")
    print(f"  Tick      : every {TICK_INTERVAL_S}s")
    print(f"  Scoring   : every {SCORE_INTERVAL_H}h")
    print(f"{'━' * 55}\n")

    # Initialise alarm manager with DB context
    manager = AlarmManager(device_id=DEVICE_ID, flask_app=flask_app)
    manager.load_from_db()

    if not manager.alarms:
        print("[main] No alarms in DB — add them via POST /api/alarms or the UI.")

    last_score_run = datetime.utcnow() - timedelta(
        hours=SCORE_INTERVAL_H
    )  # score immediately on start
    tick_count = 0

    try:
        while True:
            now = datetime.utcnow()
            tick_count += 1

            # ── Get current sleep score for smart wake ─────────────────────
            # Load only last 5 minutes of data for a lightweight score check
            df_recent = load_from_db(
                flask_app,
                DEVICE_ID,
                hours_back=0,
                start=now - timedelta(minutes=5),
                end=now,
            )
            if not df_recent.empty:
                df_recent = detect_sleep_states(df_recent)
                current_score = get_current_sleep_score(df_recent)
            else:
                current_score = 0.5

            # ── Tick alarms ────────────────────────────────────────────────
            manager.tick(current_sleep_score=current_score)

            # ── Hourly scoring run ─────────────────────────────────────────
            elapsed = (now - last_score_run).total_seconds()
            if elapsed >= SCORE_INTERVAL_H * 3600:
                run_scoring_pipeline()
                last_score_run = now

            # ── Heartbeat log every 10 ticks ───────────────────────────────
            if tick_count % 10 == 0:
                print(
                    f"[main] {now:%H:%M:%S}  tick={tick_count}  "
                    f"sleep_score={current_score:.2f}  "
                    f"alarms={len(manager.alarms)}"
                )

            time.sleep(TICK_INTERVAL_S)

    except KeyboardInterrupt:
        print("\n[main] Stopped by user.")


# ── Button stubs ───────────────────────────────────────────────────────────────
# Wire these to real GPIO button callbacks on the Pi.
# Example with RPi.GPIO:
#
#   import RPi.GPIO as GPIO
#   SNOOZE_PIN  = 17
#   DISMISS_PIN = 27
#   GPIO.setmode(GPIO.BCM)
#   GPIO.setup(SNOOZE_PIN,  GPIO.IN, pull_up_down=GPIO.PUD_UP)
#   GPIO.setup(DISMISS_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
#   GPIO.add_event_detect(SNOOZE_PIN,  GPIO.FALLING, callback=lambda _: manager.snooze_active(),  bouncetime=300)
#   GPIO.add_event_detect(DISMISS_PIN, GPIO.FALLING, callback=lambda _: manager.dismiss_active(), bouncetime=300)


def on_snooze_button(manager: AlarmManager) -> None:
    """Call this from your GPIO snooze button callback."""
    manager.snooze_active()


def on_dismiss_button(manager: AlarmManager) -> None:
    """Call this from your GPIO dismiss button callback."""
    manager.dismiss_active()


if __name__ == "__main__":
    main()
