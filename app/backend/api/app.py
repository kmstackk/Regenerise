import os
import requests
import thingsboard_api
from get_device_data import save_sensor_readings
from datetime import datetime, time as dt_time
from flask import Flask, render_template, jsonify, request
from flask_migrate import Migrate
from dotenv import load_dotenv
from models import (
    db,
    Alarm,
    AlarmEvent,
    SleepSession,
    SleepScore,
    SleepMetricScore,
    SleepMetricType,
    SensorData,
)

load_dotenv()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///app.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)
migrate = Migrate(app, db)

TB_BASE_URL = os.getenv("TB_BASE_URL")
TB_USERNAME = os.getenv("TB_USERNAME")
TB_PASSWORD = os.getenv("TB_PASSWORD")
TB_DEVICE_ID = os.getenv("TB_DEVICE_ID")


# ── Pages ──────────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    return render_template("index.html")


# ── Alarm API ──────────────────────────────────────────────────────────────────
#
# GET  /api/alarms?device_id=1        → list all alarms for a device
# POST /api/alarms                    → create a new alarm
# PUT  /api/alarms/<id>               → update an existing alarm
# DELETE /api/alarms/<id>             → delete an alarm
#
# Alarm JSON shape:
# {
#   "device_id":          1,
#   "label":              "Weekday",
#   "alarm_time":         "07:00",        HH:MM
#   "enabled":            true,
#   "smart_wakeup_window": 20,            minutes
#   "repeat_days":        "0,1,2,3,4"    comma-separated weekday ints, "" = once
# }


@app.route("/api/alarms", methods=["GET"])
def get_alarms():
    device_id = request.args.get("device_id", type=int)
    query = Alarm.query
    if device_id:
        query = query.filter_by(device_id=device_id)
    alarms = query.order_by(Alarm.alarm_time).all()
    return jsonify([_alarm_to_dict(a) for a in alarms])


@app.route("/api/alarms/<int:alarm_id>", methods=["GET"])
def get_alarm(alarm_id):
    alarm = db.session.get(Alarm, alarm_id)
    if not alarm:
        return jsonify({"error": "Alarm not found"}), 404
    return jsonify(_alarm_to_dict(alarm))


@app.route("/api/alarms", methods=["POST"])
def create_alarm():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    try:
        alarm_time = _parse_time(data.get("alarm_time", "07:00"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    alarm = Alarm(
        device_id=data.get("device_id"),
        label=data.get("label", "Alarm"),
        alarm_time=alarm_time,
        enabled=data.get("enabled", True),
        smart_wakeup_window=data.get("smart_wakeup_window", 20),
        repeat_days=data.get("repeat_days", ""),
        created_at=datetime.utcnow(),
    )
    db.session.add(alarm)
    db.session.commit()
    return jsonify(_alarm_to_dict(alarm)), 201


@app.route("/api/alarms/<int:alarm_id>", methods=["PUT"])
def update_alarm(alarm_id):
    alarm = db.session.get(Alarm, alarm_id)
    if not alarm:
        return jsonify({"error": "Alarm not found"}), 404

    data = request.get_json() or {}

    if "alarm_time" in data:
        try:
            alarm.alarm_time = _parse_time(data["alarm_time"])
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    if "label" in data:
        alarm.label = data["label"]
    if "enabled" in data:
        alarm.enabled = data["enabled"]
    if "smart_wakeup_window" in data:
        alarm.smart_wakeup_window = data["smart_wakeup_window"]
    if "repeat_days" in data:
        alarm.repeat_days = data["repeat_days"]

    db.session.commit()
    return jsonify(_alarm_to_dict(alarm))


@app.route("/api/alarms/<int:alarm_id>", methods=["DELETE"])
def delete_alarm(alarm_id):
    alarm = db.session.get(Alarm, alarm_id)
    if not alarm:
        return jsonify({"error": "Alarm not found"}), 404
    db.session.delete(alarm)
    db.session.commit()
    return jsonify({"deleted": alarm_id})


# ── Sleep session / score API ──────────────────────────────────────────────────
#
# GET /api/sleep/sessions?device_id=1&limit=30  → recent sessions with scores
# GET /api/sleep/sessions/<id>                  → single session + component scores
# GET /api/sleep/latest?device_id=1             → most recent session


@app.route("/api/sleep/sessions", methods=["GET"])
def get_sleep_sessions():
    device_id = request.args.get("device_id", type=int)
    limit = request.args.get("limit", 30, type=int)
    query = SleepSession.query
    if device_id:
        query = query.filter_by(device_id=device_id)
    sessions = query.order_by(SleepSession.start_time.desc()).limit(limit).all()
    return jsonify([_session_to_dict(s) for s in sessions])


@app.route("/api/sleep/sessions/<int:session_id>", methods=["GET"])
def get_sleep_session(session_id):
    session = db.session.get(SleepSession, session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(_session_to_dict(session, include_components=True))


@app.route("/api/sleep/latest", methods=["GET"])
def get_latest_sleep():
    device_id = request.args.get("device_id", type=int)
    query = SleepSession.query
    if device_id:
        query = query.filter_by(device_id=device_id)
    session = query.order_by(SleepSession.start_time.desc()).first()
    if not session:
        return jsonify({"error": "No sessions found"}), 404
    return jsonify(_session_to_dict(session, include_components=True))


# ── Sensor data API ────────────────────────────────────────────────────────────


@app.route("/api/sensor/latest", methods=["GET"])
def get_latest_sensor():
    device_id = request.args.get("device_id", type=int)
    query = SensorData.query
    if device_id:
        query = query.filter_by(device_id=device_id)
    row = query.order_by(SensorData.timestamp.desc()).first()
    if not row:
        return jsonify({"error": "No sensor data"}), 404
    return jsonify(
        {
            "timestamp": row.timestamp,
            "temperature": row.temperature,
            "humidity": row.humidity,
            "light": row.light,
            "sound": row.sound,
            "distance": row.distance,
            "motion": row.motion,
        }
    )


# ── Helpers ────────────────────────────────────────────────────────────────────


def _parse_time(value: str) -> dt_time:
    """Parse 'HH:MM' or 'HH:MM:SS' string into a datetime.time."""
    try:
        parts = [int(p) for p in value.split(":")]
        if len(parts) == 2:
            return dt_time(parts[0], parts[1])
        if len(parts) == 3:
            return dt_time(parts[0], parts[1], parts[2])
    except Exception:
        pass
    raise ValueError(f"Invalid time format '{value}'. Expected HH:MM.")


def _alarm_to_dict(a: Alarm) -> dict:
    return {
        "id": a.id,
        "device_id": a.device_id,
        "label": a.label,
        "alarm_time": a.alarm_time.strftime("%H:%M") if a.alarm_time else None,
        "enabled": a.enabled,
        "smart_wakeup_window": a.smart_wakeup_window,
        "repeat_days": a.repeat_days,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def _session_to_dict(s: SleepSession, include_components: bool = False) -> dict:
    # Get the most recent score for this session
    score_row = (
        SleepScore.query.filter_by(sleep_session_id=s.id)
        .order_by(SleepScore.calculated_at.desc())
        .first()
    )
    result = {
        "id": s.id,
        "device_id": s.device_id,
        "start_time": s.start_time.isoformat() if s.start_time else None,
        "end_time": s.end_time.isoformat() if s.end_time else None,
        "total_sleep_minutes": s.total_sleep_minutes,
        "sleep_efficiency": s.sleep_efficiency,
        "total_score": score_row.total_score if score_row else None,
        "algorithm_version": score_row.algorithm_version if score_row else None,
        "calculated_at": score_row.calculated_at.isoformat() if score_row else None,
    }
    if include_components and score_row:
        metrics = (
            SleepMetricScore.query.filter_by(sleep_score_id=score_row.id)
            .join(SleepMetricType)
            .all()
        )
        result["component_scores"] = {
            m.metric_type.name: {"score": m.score, "raw_value": m.raw_value}
            for m in metrics
        }
    return result


if __name__ == "__main__":
    app.run(debug=True)
