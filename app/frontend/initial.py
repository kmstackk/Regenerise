import sys
import os

# route to the backend folder from initial.py from
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend'))
api_path = os.path.join(backend_path, 'api')
sys.path.insert(0, api_path)

from flask import Flask, render_template, session, redirect, url_for, request
from flask_bootstrap import Bootstrap
from flask_wtf import FlaskForm
from models import db, Device, Alarm, SleepSession, SleepScore, SensorData, UserGoal
from datetime import datetime, timezone, time as dt_time
from send_data import add_alarm


# telemtry
from thingsboard_api import get_latest_telemetry
from get_device_data import save_sensor_readings
print("Imports finished")

app = Flask(__name__, template_folder='templates', static_folder='static')

# points at the shared database file in the backend folder
db_path = os.path.join(backend_path, 'instance', 'app.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'password'

db.init_app(app)
bootstrap = Bootstrap(app)

# getting algorithm functions needed
algos_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'algos'))
sys.path.insert(0, algos_path)
from sleep_scoring import score_sleep_efficiency, score_environmental, consistency_score
from sleep_detection import detect_sleep_states, extract_sleep_periods


# FOR NOW just having all queries to this device id, but when/if login functionality added then replace with device id
DEVICE_ID = 1

SLEEP_STAT_ICONS = [
    {"category": "uninterrupted", "icon": "doublebed.svg"},
    {"category": "restlessness", "icon": "closedeye.svg"},   
    {"category": "environment", "icon": "audiolines.svg"},
]

DAY_MAP = {'1': 'Monday', '2': 'Tuesday', '3': 'Wednesday', '4': 'Thursday', '5': 'Friday', '6': 'Saturday', '7': 'Sunday'}


# HELPERS 

# Returns the three sleep stats in box 1 on the home page
def get_sleep_stats(device_id):
    # failsafe values
    hours, restlessness, env_score = 7.5, 19, 2

    session = (SleepSession.query.filter_by(device_id=device_id).order_by(SleepSession.start_time.desc()).first())

    if session:
        try:
            hours = round(session.total_sleep_minutes / 60, 1) if session.total_sleep_minutes else 0
            
            # Get SensorData for session 
            rows = SensorData.query.filter(
                SensorData.device_id == device_id, 
                SensorData.timestamp >= session.start_time.timestamp() * 1000,
                SensorData.timestamp <= session.end_time.timestamp() * 1000
            ).order_by(SensorData.timestamp).all()
            
            # Convert to a dataframe as algorithm structure
            df = pd.DataFrame([{
                "timestamp": r.timestamp,
                "temperature": r.temperature,
                "humidity": r.humidity,
                "light": r.light,
                "sound": r.sound,
                "distance": r.distance,
                "motion": r.motion,
            } for r in rows])

            # Convert timestamp to datetime
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df = df.set_index("timestamp")

            # Run sleep detection and extract periods
            df = detect_sleep_states(df)
            periods = extract_sleep_periods(df)

            # Score
            restlessness = score_sleep_efficiency(periods)
            env_score, env_band = score_environmental(df, periods)

        # failsafe
        except Exception as e:
            print("Sleep scoring failed: ", e)
        
    
    scores = [hours, restlessness, env_score]
    for x, icon_row in enumerate(SLEEP_STAT_ICONS):
        icon_row['userscore'] = scores[x]

    return SLEEP_STAT_ICONS


def get_overall_score(device_id):
    # will return 'excellent', 'good', 'fair' or 'poor' from recent sleepscore
    latest = (SleepScore.query.join(SleepScore.sleep_session).filter(SleepSession.device_id == device_id).order_by(SleepScore.calculated_at.desc()).first())

    if latest and latest.total_score is not None:
        if latest.total_score >= 0.85:
            return "excellent"
        elif latest.total_score >= 0.7:
            return "good"
        elif latest.total_score >= 0.4:
            return "fair"
        else:
            return "poor"
    
    # failsafe
    return "good"


def get_sleep_consistency(device_id, nights=7):
    # Get last N sleep sessions
    sessions = (SleepSession.query.filter_by(device_id=device_id).order_by(SleepSession.start_time.desc()).limit(nights).all())

    if not sessions or len(sessions) < 2:
        return 0.5  # fallback

    nightly_onsets = [s.start_time for s in sessions]
    nightly_wakes = [s.end_time for s in sessions]

    try:
        return consistency_score(nightly_onsets, nightly_wakes)
    except Exception as e:
        print("Consistency score failed:", e)
        return 0.5


def get_consistency_label(score):
    if score >= 0.75:
        return "Excellent"
    elif score >= 0.55:
        return "Good"
    elif score >= 0.35:
        return "Fair"
    else:
        return "Poor"


def get_or_create_user_goal(device_id):
    user_goal = UserGoal.query.filter_by(device_id=device_id).first()
    
    # Create a blank user goal if no goal exists yet 
    if not user_goal:
        user_goal = UserGoal(device_id=device_id, goal=None, goal_percent=0)
        db.session.add(user_goal)
        db.session.commit()
    return user_goal

def get_alarms_for_display(device_id):
    # Returns alarms for device ordered by time
    return(Alarm.query
           .filter_by(device_id=device_id)
           .order_by(Alarm.alarm_time).all())

@app.template_filter('format_days')
def format_days(repeat_days):
    if not repeat_days:
        return 'Once'
    else:
        days = sorted(set(repeat_days)) # removes duplicates and sorts numerically
    
    if days == ['1', '2', '3', '4', '5']:
        return 'Weekdays'
    elif days == ['6', '7']:
        return 'Weekends'
    elif days == ['1', '2', '3', '4', '5', '6', '7']:
        return 'Everyday'
    else:
        return ', '.join(DAY_MAP[x] for x in days if x in DAY_MAP)



# ROUTES

@app.route('/')
def homePage():
    device = Device.query.get(DEVICE_ID)
    name = device.device_name if device else "Name"

    sleep_data = get_sleep_stats(DEVICE_ID)
    overall = get_overall_score(DEVICE_ID)
    alarms = get_alarms_for_display(DEVICE_ID) 
    return render_template('home.html', data=sleep_data, user_name=name, user_overall_score=overall, alarms=alarms)


@app.route("/api/data")
def get_thingsboard_data():

    try:
        payload = get_telemetry()
        save_sensor_readings(DEVICE_ID, payload)
        return {"status": "ok"}, 200

    except Exception as e:
        return {"error": str(e)}, 500


@app.route('/regenerise/sleep-stats')
def statsPage():
    return render_template('stats.html', data=get_sleep_stats(DEVICE_ID))

@app.route('/regenerise/recent-overview')
def overviewPage():
    return render_template('overview.html')

@app.route('/regenerise/alarms')
def alarmPage():
    alarms = get_alarms_for_display(DEVICE_ID)
    return render_template('alarms.html', alarms=alarms)

@app.route('/regenerise/info')
def infodoc():
    alarms = get_alarms_for_display(DEVICE_ID)
    return render_template('infodoc.html')


# SLEEP GOALS

@app.route('/regenerise/sleep-goals')
def goalsPage():
    user_goal = get_or_create_user_goal(DEVICE_ID)

    # Converting goal_percent to SVG fill length, circle radius in SVG is 38 so d = 2 * 3.14 * 38 = 239
    fill_length = int((user_goal.goal_percent or 0) / 100 * 239)

    session = (SleepSession.query.filter_by(device_id=DEVICE_ID).order_by(SleepSession.start_time.desc()).first())

    try:
        score = get_sleep_consistency(DEVICE_ID)
        schedule_rating = get_consistency_label(score)  # db sleep consistency score

        wake_time = session.start_time
        sleep_time = session.end_time

    except Exception as e:
        schedule_rating = "Good"
        wake_time = "8:15 am"
        sleep_time = "10:30 pm"

    # currently hardcoded, replace with real DB queries when we get to that
    metrics = {
        "schedule_rating": schedule_rating, 
        "wake_time": wake_time,
        "sleep_time": sleep_time,
        
        # These are placeholders for now
        "light_hours": 4.2, 
        "meal_consistency": None,
        "exercise": None
    }
    return render_template('goals.html', user_goal=user_goal.goal, goal_percent=user_goal.goal_percent or 87, goal_progress=fill_length, metrics=metrics)

@app.route('/set-goal', methods=['POST'])
def setGoal():
    # Gets the 'goal' from goals.html where name="goal"
    chosen_goal = request.form.get('goal')

    # Line to get the current goal value from the database. (1) references the user whose id column equals 1. If no row exists it returns None.
    user_goal = get_or_create_user_goal(DEVICE_ID)
    user_goal.goal = chosen_goal # updates database 'goal' column
    user_goal.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    return redirect(url_for('goalsPage'))


# ALARMS

@app.route('/regenerise/alarms/add', methods=['POST'])
def addAlarm():
    time_str = request.form.get('alarm_time') # e.g. "07:15" from <input type="time">
    days = request.form.getlist('days')      # list of checked values e.g. ['1','5']
    label = request.form.get('label', '').strip() or None

    parsed_time = None 
    if time_str:
        try:
            hour, min = time_str.split(':')
            parsed_time = dt_time(int(hour), int(min)) 
        except ValueError:
            pass

    # Sort and join day digits into db format
    repeat_days = ''.join(sorted(set(days))) if days else None

    new_alarm = Alarm(
        device_id=DEVICE_ID,
        alarm_time=parsed_time,
        enabled=True,
        repeat_days=repeat_days,
        label=label,
        created_at=datetime.now(timezone.utc),
    )
    db.session.add(new_alarm)
    db.session.commit()
    add_alarm(time_str, True)

    return redirect(url_for('alarmPage'))

# Flips the enabled boolean and saves to db
@app.route('/regenerise/alarms/toggle/<int:alarm_id>', methods=['POST'])
def toggleAlarm(alarm_id):
    alarm = Alarm.query.get_or_404(alarm_id)
    alarm.enabled = not alarm.enabled
    db.session.commit()
    return redirect(url_for('alarmPage'))

@app.route('/regenerise/alarms/delete/<int:alarm_id>', methods=['POST'])
def deleteAlarm(alarm_id):
    alarm = Alarm.query.get_or_404(alarm_id)
    db.session.delete(alarm)
    db.session.commit()
    return redirect(url_for('alarmPage'))


if __name__ == '__main__':
    with app.app_context():
        # Creates any missing tables without touching existing ones 
        # So on first run UserGoal will be created here
        db.create_all()
        
    app.run(port=5001, debug=False)
