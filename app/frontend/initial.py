import sys
import os

# route to the backend folder from initial.py from
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend'))
sys.path.insert(0, backend_path)

from flask import Flask, render_template, session, redirect, url_for, request
from flask_bootstrap import Bootstrap
from flask_wtf import FlaskForm
from models import db, Device, Alarm, SleepSession, SleepScore, SensorData, UserGoal
from datetime import datetime, timezone

# telemtry
from thingsboard_api import get_telemetry
from get_device_data import save_sensor_readings

app = Flask(__name__, template_folder='templates', static_folder='static')

# points at the shared database file in the backend folder
db_path = os.path.join(backend_path, 'database.db')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///data.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'password'

db.init_app(app)
bootstrap = Bootstrap(app)

# FOR NOW just having all queries to this device id, but when/if login functionality added then replace with device id
DEVICE_ID = 1

SLEEP_STAT_ICONS = [
    {"category": "uninterrupted", "icon": "doublebed.svg"},
    {"category": "restlessness", "icon": "closedeye.svg"},   
    {"category": "environment", "icon": "audiolines.svg"},
]

# Returns the three sleep stats in box 1 on the home page
def get_sleep_stats(device_id):
    session = (SleepSession.query.filter_by(device_id=device_id).order_by(SleepSession.start_time.desc()).first())

    if session:
        if session.total_sleep_minutes:
            hours = round(session.total_sleep_minutes / 60, 1)
        else:
            hours = 0

        # idk what is going on with restlessness (minutes) so for now I'm picking whatever number I like 
        restlessness = 20
    
        # im also not really sure how we are calculating enviroment score so that is also dummy values for now
        env_score = 3

    # failsafe for now
    else:
        hours, restlessness, env_score = 8, 20, 3
    
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
    
    # default while database empty
    return "excellent"


def get_or_create_user_goal(device_id):
    user_goal = UserGoal.query.filter_by(device_id=device_id).first()
    
    # Create a blank user goal if no goal exists yet 
    if not user_goal:
        user_goal = UserGoal(device_id=device_id, goal=None, goal_percent=0)
        db.session.add(user_goal)
        db.session.commit()
    return user_goal


# user_name and user_overall_score are dummy values currently 
@app.route('/')
def homePage():
    device = Device.query.get(DEVICE_ID)
    name = device.device_name if device else "Name"

    sleep_data = get_sleep_stats(DEVICE_ID)
    overall = get_overall_score(DEVICE_ID)
    alarms = Alarm.query.filter_by(device_id=DEVICE_ID).all()
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
    return render_template('alarms.html')

@app.route('/regenerise/sleep-goals')
def goalsPage():
    user_goal = get_or_create_user_goal(DEVICE_ID)

    # Converting goal_percent to SVG fill length, circle radius in SVG is 38 so d = 2 * 3.14 * 38 = 239
    fill_length = int((user_goal.goal_percent or 0) / 100 * 239)

    # currently hardcoded, replace with real DB queries when we get to that
    metrics = {
        "schedule_rating": "Good",
        "wake_time": "8:15 am",
        "sleep_time": "10:30 pm", 
        "light_hours": 4.2,
        "meal_consistency": None,
        "exercise": None
    }
    return render_template('goals.html', user_goal=user_goal.goal, goal_percent=user_goal.goal_percent or 0, goal_progress=fill_length, metrics=metrics)

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

if __name__ == '__main__':
    with app.app_context():
        # Creates any missing tables without touching existing ones 
        # So on first run UserGoal will be created here
        db.create_all()
        
    app.run(debug=True)
