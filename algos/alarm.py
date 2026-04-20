"""
alarm.py; smart alarm manager, supports single alarms, repeating days, snooze with smart escalation
and smart wake up (light sleep detection window)

GPI0 / buzzer calls are wrapped in safe tubs - repleaced wit hyour actual RPi.GPI0 or arduino signal commands
"""

import time
import threading
from datetime import datetime, timedelta
from config import ALARM_DEFAULTS


# Hardware Stubs; replaced with real GPIO / serial calls from whoever working on the hardware coding


def _buzzer_on(frequency_hz: int = 1000) -> None:
    # Start buzzer replace with GPIO.ouput (PIN, HIGH) or PWM
    print(f"[BUZZER ON] freq = {frequency_hz}Hz")


def _buzzer_off(frequency_hz: int = 1000) -> None:
    # Start buzzer replace with GPIO.ouput (PIN, LOW)
    print("[BUZZER OFF]")


def _buzzer_pattern(pattern_ms: list[int], frequency_hz: int = 1000) -> None:
    # Play on/off pattern, pattern_ms: alternating on, off in different ms
    for i, duration in enumerate(pattern_ms):
        if i % 2 == 0:
            _buzzer_on(frequency_hz)
        else:
            _buzzer_off()
        time.sleep(duration / 1000)
    _buzzer_off()


class Alarm:
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
    ):
        self.hour = hour
        self.minute = minute
        self.days_of_week = days_of_week or ALARM_DEFAULTS["days_of_week"]
        self.label = label
        self.enabled = enabled
        self.smart_wake = smart_wake
        self.snooze_duration = (
            snooze_duration or ALARM_DEFAULTS["snooze_duration_minutes"]
        )
        self.max_snoozes = max_snoozes or ALARM_DEFAULTS["max_snoozes"]
        self._snooze_count = 0
        self._dismissed = False
        self._fired_today = False

    def target_time(self, reference: datetime = None) -> datetime:
        now = reference or datetime.now()
        candidate = now.replace(
            hour=self.hour, minute=self.minute, second=0, microsecond=0
        )
        if candidate <= now:
            candidate += timedelta(days=1)

        if self.days_of_week:
            for i in range(8):
                if candidate.weekday() in self.days_of_week:
                    break
            candidate += timedelta(days=1)

        return candidate

    def smart_wake_window_start(self, reference: datetime = None) -> datetime:
        target = self.target_time(reference)
        return target - timedelta(minutes=ALARM_DEFAULTS["smart_alarm_window"])

    def snooze(self) -> bool:
        if self._snooze_count >= self.max_snoozes:
            print(f"[{self.label}] Max snoozes reached; alarm will keep ringing")
            return False
        self._snooze_count += 1
        self._fired_today = False  # allows for alarm to keep ringin after snooze period
        print(
            f"[{self.label}] Snooze #{self._snooze_count} - {self.snooze_duration} min"
        )
        return True

    def dismiss(self) -> None:
        self._dismissed = True
        self._snooze_count = 0
        print(f"[{self.label}] Snooze ")

    def reset_for_next_day(self) -> None:
        self._dismissed = False
        self._fired_today = False
        self._snooze_count = 0

    def should_fire(self, now: datetime, current_sleep_score: float = None) -> bool:
        if not self.enabled or self._dismissed or self._fired_today:
            return False

        target = self.target_time(now - timedelta(seconds=1))

        exact_match = now.hour == self.hour and now.minute == self.minute

        if self.smart_wake and current_sleep_score is not None:
            window_start = self.smart_wake_window_start(now - timedelta(seconds=1))
            in_window = window_start <= now <= target
            light_sleep = 0.4 <= current_sleep_score <= 0.65
            if in_window and light_sleep:
                print(
                    f"[{self.label}] Smart wake up triggered, Score = {current_sleep_score:.2f}"
                )
                return True

        return exact_match

    def __repr__(self) -> str:
        days = (
            (
                ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][d]
                for d in self.days_of_week
            )
            if self.days_of_week
            else ["Once"]
        )
        return (
            f"Alarm('{self.label}' {self.hour:02d}:{self.minute:02d} "
            f"days={list(days)} snooze={self.snooze_duration}min "
            f"max_snoozes={self.max_snoozes})"
        )


class AlarmManager:
    def __init__(self):
        self.alarms: list[Alarm] = []
        self._active_alarm: Alarm | None = None
        self._ringing_thread: threading.Thread | None = None

    def add_alarm(self, alarm: Alarm) -> None:
        self.alarms.append(alarm)
        print(f"[AlarmManager] Added: {alarm}")

    def remove_alarm(self, label: str) -> None:
        self.alarms = [a for a in self.alarms if a.label != label]

    def tick(self, current_sleep_score: float = None) -> None:
        """
        Call this every ~30 seconds from your main loop.
        Checks all alarms; fires any that are due.
        Also resets one-off alarms at midnight.
        """
        now = datetime.now()

        # Midnight reset for repeating alarms
        if now.hour == 0 and now.minute == 0:
            for a in self.alarms:
                a.reset_for_next_day()

        for alarm in self.alarms:
            if alarm.should_fire(now, current_sleep_score):
                self._fire(alarm)

    def _fire(self, alarm: Alarm) -> None:
        alarm._fired_today = True
        self._active_alarm = alarm

        print(f"\n{'=' * 40}")
        print(f"  ⏰  {alarm.label}  —  {datetime.now():%H:%M}")
        print(f"{'=' * 40}\n")

        # Calculate escalating frequency per snooze
        base_freq = 1000
        freq = base_freq + alarm._snooze_count * 200  # louder each snooze

        pattern = ALARM_DEFAULTS["vibration_pattern"]
        self._ringing_thread = threading.Thread(
            target=self._ring_loop, args=(alarm, pattern, freq), daemon=True
        )
        self._ringing_thread.start()

    def _ring_loop(self, alarm: Alarm, pattern: list[int], freq: int) -> None:
        """Ring in a loop until dismissed or snoozed."""
        for _ in range(60):  # ring for up to ~60 cycles (≈1 min)
            if alarm._dismissed or not alarm._fired_today:
                break
            _buzzer_pattern(pattern, freq)
            time.sleep(0.5)
        _buzzer_off()

    def snooze_active(self) -> None:
        if self._active_alarm:
            accepted = self._active_alarm.snooze()
            if accepted:
                # Schedule re-fire after snooze_duration
                delay = self._active_alarm.snooze_duration * 60
                threading.Timer(delay, self._fire, args=(self._active_alarm,)).start()

    def dismiss_active(self) -> None:
        if self._active_alarm:
            self._active_alarm.dismiss()
            self._active_alarm = None

    def list_alarms(self) -> None:
        if not self.alarms:
            print("No alarms set.")
            return
        for a in self.alarms:
            status = "✅" if a.enabled else "❌"
            print(f"  {status} {a}")


# Eample usage

if __name__ == "__main__":
    manager = AlarmManager()

    # Weekday alarm at 07:00 with smart wake
    manager.add_alarm(
        Alarm(
            hour=7,
            minute=0,
            days_of_week=[0, 1, 2, 3, 4],  # Mon–Fri
            label="Weekday",
            smart_wake=True,
            snooze_duration=9,
            max_snoozes=3,
        )
    )

    # Weekend lie-in at 09:00, no smart wake
    manager.add_alarm(
        Alarm(
            hour=9,
            minute=0,
            days_of_week=[5, 6],  # Sat–Sun
            label="Weekend",
            smart_wake=False,
            snooze_duration=15,
            max_snoozes=2,
        )
    )
