"""
Config.py; Sleep tracker configuration
All thresholds, weights, score bands and also alaram settings stored here
Edit this file to tune/change the system without editing the code to much
"""

# Scoring weights
SCORE_WEIGHTS: dict = {
    "sleep_duration": 0.25,  # Total hours slept
    "sleep_efficiency": 0.20,  # Hours slept / time in bed
    "environmental": 0.20,  # Temp, humidity, light, sound
    "restfulness_index": 0.20,  # Movement variance (how much movement) overnight
    "breathing": 0.10,  # Breathing rate/speed
    "snoring_coughing": 0.05,  # Noises made by the sleeper
}


# Score bands: label + emoji to be shown on the website/report
SCORE_BANDS: list[dict] = [
    {"min": 0.85, "max": 1.00, "label": "Excellent", "emoji": "🌟"},
    {"min": 0.70, "max": 0.85, "label": "Good", "emoji": "✅"},
    {"min": 0.55, "max": 0.70, "label": "Fair", "emoji": "⚠️"},
    {"min": 0.40, "max": 0.55, "label": "Poor", "emoji": "😴"},
    {"min": 0.00, "max": 0.40, "label": "Very Poor", "emoji": "❌"},
]


# Sleep detection thresholds (awake and sleep)
SLEEP_DETECTION: dict = {
    # light sensor
    "light_sleep_threshold": 50,
    "light_awake_threshold": 150,
    # Sound sensor
    "sound_sleep_threshold": 120,
    "sound_change_occur_threshold": 300,  # this is for if any sounds occur such as snoring, coughing talking etc
    "sound_snore_threshold": 200,
    # Motion sensor
    "motion_active_threshold": 1,
    "distance_change_threshold": 50,  # mm change = restless/movement
    "distance_sleep_max": 300,  # below this someone is in the bed
    # Temperature sensor
    "temp_ideal_min": 16.0,
    "temp_ideal_max": 19.0,
    "temp_acceptable_min": 14.0,
    "temp_acceptable_max": 22.0,
    # Event timing
    "min_sleep_window_min": 30,  # min 30 min consecutive quiet/low movement = asleep
    "wake_event_gap_min": 5,  # Gap between awake events to count as awake
    "sample_interval_secs": 10,  # Expected polling interval from sensors
}


# Ideal environmental thresholds
ENVIRONMENT: dict = {
    "temperature": {
        "ideal": (16.0, 19.0),
        "acceptable": (14.0, 22.0),
    },
    "humidity": {
        "ideal": (40.0, 60.0),
        "acceptable": (30.0, 70.0),
    },
    "light": {
        "ideal_max": 30,
        "acceptable_max": 80,
    },
    "sound": {
        "ideal_max": 120,
        "acceptable_max": 200,
    },
}


# Consistency Snoring
CONSISTENCY: dict = {
    "set_bedtime_tolerance_min": 30,  # Set bedtime for scoring
    "waketime_tolerance_min": 30,
    "min_nights_required": 3,  # Need at least N number of nights to computer scores
}


# Alarm setting defaults
ALARM_DEFAULTS: dict = {
    "snooze_duration_min": 9,
    "max_snoozes": 3,
    "snooze_escalation": True,  # alarm louder per snooze
    "smart_alarm_window": 20,  # Wake within 20 min of alarm if light sleep
    "wake_up_check": True,  # Check/confirm if user awake, if not done alarm goes off again
    "days_of_week": [],  # Empty = one-off. [0..6] = Mon..Sun
}


# Restlessness config
RESTLESSNESS: dict = {
    "movement_event_threshold": 1,
    "distance_spike_threshold": 100,
    "restless_window_seconds": 60,
}


# Sleep duration
SLEEP_DURATION: dict = {
    "ideal_min": 7.0,
    "ideal_max": 9.0,
    "acceptable_min": 6.0,
    "acceptable_max": 10.0,
    "min_valid": 2.0,
}
