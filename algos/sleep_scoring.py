"""
Sleep scoring, weighted sleep algorithm
implements weighted model in IOT doc and calcs all the output ints
"""

import numpy as np
import pandas as pd
from datetime import timedelta
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
