"""
alarm.py — Smart alarm manager.
Supports single alarms, repeating days, snooze with smart escalation,
and smart wake-up (light sleep detection window).

GPIO / buzzer calls are wrapped in safe stubs — replace with real
RPi.GPIO or Arduino serial commands in hardware/main.py.

Changes from original:
  - Fixed bug in target_time(): for/break loop was broken (missing break indent)
  - Fixed key mismatch: snooze_duration_min → snooze_duration_minutes (matches config.py)
  - AlarmManager now accepts device_id and can load alarms from the Flask DB
  - Fired / snoozed / dismissed events are written to alarm_events table
  - Hourly DB reload picks up new/deleted alarms without restarting the Pi
"""

import time
import threading
from datetime import datetime, timedelta
from config import ALARM_DEFAULTS


# ── Hardware stubs ─────────────────────────────────────────────────────────────
# Replace these with real GPIO / serial calls in hardware/main.py


def _buzzer_on(frequency_hz: int = 1000) -> None:
    """Start buzzer. Replace with GPIO.output(PIN, HIGH) or PWM."""
    print(f"[BUZZER ON] freq={frequency_hz}Hz")


def _buzzer_off() -> None:
    """Stop buzzer. Replace with GPIO.output(PIN, LOW)."""
    print("[BUZZER OFF]")


def _buzzer_pattern(pattern_ms: list[int], frequency_hz: int = 1000) -> None:
    """Play alternating on/off pattern. pattern_ms = [on_ms, off_ms, ...]"""
    for i, duration in enumerate(pattern_ms):
        if i % 2 == 0:
            _buzzer_on(frequency_hz)
        else:
            _buzzer_off()
        time.sleep(duration / 1000)
    _buzzer_off()


# ── Alarm class ────────────────────────────────────────────────────────────────


class Alarm:
    """
    Single alarm configuration.

    Parameters
    ----------
    hour, minute : int
    days_of_week : list[int]  0=Mon … 6=Sun. Empty = fire once.
    label        : str
    enabled      : bool
    smart_wake   : bool       fire early if person is in light sleep
    snooze_duration : int     minutes (overrides config default)
    max_snoozes  : int
    db_id        : int | None  primary key from alarms table (set by load_from_db)
    smart_wakeup_window : int  minutes before alarm where smart wake can trigger
    """

    def __init__(
        self,
        hour: int,
        minute: int,
        days_of_week: list[int] = None,
        label: str = "Alarm",
        enabled: bool = True,
        smart_wake: bool = True,
        snooze_duration: int = None,
        max_snoozes: int = None,
        db_id: int = None,
        smart_wakeup_window: int = None,
    ):
        self.hour = hour
        self.minute = minute
        self.days_of_week = days_of_week or ALARM_DEFAULTS["days_of_week"]
        self.label = label
        self.enabled = enabled
        self.smart_wake = smart_wake
        # FIX: was reading "snooze_duration_min" which didn't exist in config
        self.snooze_duration = (
            snooze_duration or ALARM_DEFAULTS["snooze_duration_minutes"]
        )
        self.max_snoozes = max_snoozes or ALARM_DEFAULTS["max_snoozes"]
        self.smart_wakeup_window = (
            smart_wakeup_window or ALARM_DEFAULTS["smart_alarm_window"]
        )
        self.db_id = db_id  # set when loaded from DB

        self._snooze_count = 0
        self._dismissed = False
        self._fired_today = False

    def target_time(self, reference: datetime = None) -> datetime:
        """Next scheduled alarm datetime from reference (default = now)."""
        now = reference or datetime.now()
        candidate = now.replace(
            hour=self.hour, minute=self.minute, second=0, microsecond=0
        )
        if candidate <= now:
            candidate += timedelta(days=1)

        if self.days_of_week:
            # FIX: original loop was missing the break inside the if, so it
            # always advanced by one extra day regardless of match.
            for _ in range(8):
                if candidate.weekday() in self.days_of_week:
                    break
                candidate += timedelta(days=1)

        return candidate

    def smart_wake_window_start(self, reference: datetime = None) -> datetime:
        """Earliest the alarm may fire in smart mode."""
        target = self.target_time(reference)
        return target - timedelta(minutes=self.smart_wakeup_window)

    def snooze(self) -> bool:
        """Returns True if snooze accepted, False if max reached."""
        if self._snooze_count >= self.max_snoozes:
            print(f"[{self.label}] Max snoozes reached — alarm will keep ringing.")
            return False
        self._snooze_count += 1
        self._fired_today = False  # allows re-fire after snooze period
        print(
            f"[{self.label}] Snooze #{self._snooze_count} — {self.snooze_duration} min"
        )
        return True

    def dismiss(self) -> None:
        self._dismissed = True
        self._snooze_count = 0
        print(f"[{self.label}] Alarm dismissed.")

    def reset_for_next_day(self) -> None:
        self._dismissed = False
        self._fired_today = False
        self._snooze_count = 0

    def should_fire(self, now: datetime, current_sleep_score: float = None) -> bool:
        """True if this alarm should fire right now."""
        if not self.enabled or self._dismissed or self._fired_today:
            return False

        target = self.target_time(now - timedelta(seconds=1))
        exact_match = now.hour == self.hour and now.minute == self.minute

        if self.smart_wake and current_sleep_score is not None:
            window_start = self.smart_wake_window_start(now - timedelta(seconds=1))
            in_window = window_start <= now <= target
            light_sleep = 0.40 <= current_sleep_score <= 0.65
            if in_window and light_sleep:
                print(
                    f"[{self.label}] Smart wake triggered (score={current_sleep_score:.2f})"
                )
                return True

        return exact_match

    def __repr__(self) -> str:
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        days = (
            [day_names[d] for d in self.days_of_week] if self.days_of_week else ["Once"]
        )
        return (
            f"Alarm('{self.label}' {self.hour:02d}:{self.minute:02d} "
            f"days={days} snooze={self.snooze_duration}min "
            f"max_snoozes={self.max_snoozes})"
        )


# ── AlarmManager ───────────────────────────────────────────────────────────────


class AlarmManager:
    """
    Manages a list of Alarm objects.

    Call tick() every ~30 seconds from the main loop.
    Alarms are loaded from the Flask database via load_from_db().
    Fired / snoozed / dismissed events are written back to alarm_events.
    """

    def __init__(self, device_id: int = None, flask_app=None):
        """
        Parameters
        ----------
        device_id : int     — DB device id, required for DB operations
        flask_app : Flask   — the Flask app instance, needed for app_context()
                              when running outside the web process (e.g. on Pi)
        """
        self.device_id = device_id
        self.flask_app = flask_app
        self.alarms: list[Alarm] = []

        self._active_alarm: Alarm | None = None
        self._active_event_id: int | None = None
        self._ringing_thread: threading.Thread | None = None

    # ── Loading from DB ───────────────────────────────────────────────────────

    def load_from_db(self) -> None:
        """
        Pull all enabled alarms for device_id from the alarms table and
        replace the in-memory list. Safe to call repeatedly — idempotent.
        Requires flask_app to be set so we can push an app context.
        """
        if self.device_id is None or self.flask_app is None:
            print("[AlarmManager] No device_id/flask_app — skipping DB load.")
            return

        from models import db, Alarm as AlarmModel

        with self.flask_app.app_context():
            db_alarms = AlarmModel.query.filter_by(
                device_id=self.device_id, enabled=True
            ).all()
            loaded = []
            for a in db_alarms:
                # repeat_days stored as e.g. "0,1,2,3,4" or "" for one-off
                days = (
                    [int(d) for d in a.repeat_days.split(",") if d.strip()]
                    if a.repeat_days
                    else []
                )
                # smart_wakeup_window was dropped in migration 5c2c248b5c58
                # so we fall back to config default if the column is missing
                smart_window = (
                    getattr(a, "smart_wakeup_window", None)
                    or ALARM_DEFAULTS["smart_alarm_window"]
                )

                alarm = Alarm(
                    hour=a.alarm_time.hour,
                    minute=a.alarm_time.minute,
                    days_of_week=days,
                    label=a.label or f"Alarm-{a.id}",
                    enabled=a.enabled,
                    smart_wake=smart_window > 0,
                    smart_wakeup_window=smart_window,
                    db_id=a.id,
                )
                loaded.append(alarm)

        self.alarms = loaded
        print(f"[AlarmManager] Loaded {len(self.alarms)} alarm(s) from DB.")

    def add_alarm(self, alarm: Alarm) -> None:
        """Add alarm manually (for testing without a DB)."""
        if not hasattr(alarm, "db_id") or alarm.db_id is None:
            alarm.db_id = None
        self.alarms.append(alarm)
        print(f"[AlarmManager] Added: {alarm}")

    def remove_alarm(self, label: str) -> None:
        self.alarms = [a for a in self.alarms if a.label != label]

    # ── Main tick ─────────────────────────────────────────────────────────────

    def tick(self, current_sleep_score: float = None) -> None:
        """
        Call every ~30 seconds from the hardware main loop.
        - Checks all alarms and fires any that are due
        - Resets one-off alarms at midnight
        - Reloads from DB once per hour to pick up changes without restart
        """
        now = datetime.now()

        # Midnight reset
        if now.hour == 0 and now.minute == 0:
            for a in self.alarms:
                a.reset_for_next_day()

        # Hourly reload from DB
        if now.minute == 0 and now.second < 35:
            self.load_from_db()

        for alarm in self.alarms:
            if alarm.should_fire(now, current_sleep_score):
                self._fire(alarm)

    # ── Fire / ring ───────────────────────────────────────────────────────────

    def _fire(self, alarm: Alarm) -> None:
        alarm._fired_today = True
        self._active_alarm = alarm
        fired_at = datetime.utcnow()

        print(f"\n{'=' * 40}")
        print(f"  ⏰  {alarm.label}  —  {datetime.now():%H:%M}")
        print(f"{'=' * 40}\n")

        # Write alarm_event row to DB
        if alarm.db_id and self.device_id and self.flask_app:
            try:
                from models import db, AlarmEvent

                with self.flask_app.app_context():
                    ev = AlarmEvent(
                        alarm_id=alarm.db_id,
                        device_id=self.device_id,
                        triggered_at=fired_at,
                        snoozed=False,
                    )
                    db.session.add(ev)
                    db.session.commit()
                    self._active_event_id = ev.id
            except Exception as e:
                print(f"[AlarmManager] Could not write alarm event: {e}")

        # Escalating frequency per snooze
        freq = 1000 + alarm._snooze_count * 200
        pattern = ALARM_DEFAULTS["vibration_pattern"]
        self._ringing_thread = threading.Thread(
            target=self._ring_loop, args=(alarm, pattern, freq), daemon=True
        )
        self._ringing_thread.start()

    def _ring_loop(self, alarm: Alarm, pattern: list[int], freq: int) -> None:
        """Ring in a loop until dismissed or snoozed (max ~1 min)."""
        for _ in range(60):
            if alarm._dismissed or not alarm._fired_today:
                break
            _buzzer_pattern(pattern, freq)
            time.sleep(0.5)
        _buzzer_off()

    # ── User interactions ─────────────────────────────────────────────────────

    def snooze_active(self) -> None:
        """Call when the user presses the snooze button."""
        if not self._active_alarm:
            return
        accepted = self._active_alarm.snooze()
        if accepted:
            # Mark event as snoozed in DB
            if self._active_event_id and self.flask_app:
                try:
                    from models import db, AlarmEvent

                    with self.flask_app.app_context():
                        ev = db.session.get(AlarmEvent, self._active_event_id)
                        if ev:
                            ev.snoozed = True
                            db.session.commit()
                except Exception as e:
                    print(f"[AlarmManager] Could not update snooze: {e}")

            delay = self._active_alarm.snooze_duration * 60
            threading.Timer(delay, self._fire, args=(self._active_alarm,)).start()

    def dismiss_active(self) -> None:
        """Call when the user presses the dismiss button."""
        if not self._active_alarm:
            return
        self._active_alarm.dismiss()

        # Write dismissed_at to DB
        if self._active_event_id and self.flask_app:
            try:
                from models import db, AlarmEvent

                with self.flask_app.app_context():
                    ev = db.session.get(AlarmEvent, self._active_event_id)
                    if ev:
                        ev.dismissed_at = datetime.utcnow()
                        ev.snoozed = False
                        db.session.commit()
            except Exception as e:
                print(f"[AlarmManager] Could not update dismiss: {e}")

        self._active_alarm = None
        self._active_event_id = None

    def list_alarms(self) -> None:
        if not self.alarms:
            print("No alarms set.")
            return
        for a in self.alarms:
            status = "✅" if a.enabled else "❌"
            print(f"  {status} {a}")
