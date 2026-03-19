weights = {
    "sleep_duration": 0.25,
    "sleep_efficiency": 0.20,
    "environmental_factors": 0.20,
    "physiological_stability": 0.10,
    "restfulness_index": 0.20,
    "snoring_coughing": 0.05
} # values used from IoT project doc

environmental_weights = {
    "temperature": 0.40, # placeholder
    "humidity": 0.20, # placeholder
    "light": 0.20, # placeholder
    "sound": 0.20 # placeholder
}

ideal_environmental_ranges = {
    "temperature": (0,0), # placeholder
    "humidity": (0,0), # placeholder
    "light": (0,0), # placeholder
    "sound": (0,0) # placeholder
}

sleep_detection_thresholds = {
    "movement_max": 0, # placeholder
    "light_max": 0, # placeholder, however take into account sunset/sunrise
}

sleep_duration_target = 8 # hrs
efficiency_threshold = 0.85 # 85% spent asleep is perfect score?

score_bands = {
    "excellent": 85,
    "good": 70,
    "average": 60,
    "poor": 40
} # can be changed later
