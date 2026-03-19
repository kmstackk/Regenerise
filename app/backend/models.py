from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Device(db.Model):
    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)
    device_name = db.Column(db.String(100))
    device_type = db.Column(db.String(50))
    serial_number = db.Column(db.String(100), unique=True)
    status = db.Column(db.String(50))
    registered_at = db.Column(db.DateTime)
    last_seen = db.Column(db.DateTime)

    location_id = db.Column(db.Integer, db.ForeignKey("locations.id"))
    firmware_version_id = db.Column(db.Integer, db.ForeignKey("firmware_versions.id"))

    location = db.relationship("Location", back_populates="devices")
    firmware_version = db.relationship("FirmwareVersion", back_populates="devices")
    device_configurations = db.relationship("DeviceConfiguration", back_populates="devices")
    sensors = db.relationship("Sensor", back_populates="devices")
    device_status_logs = db.relationship("DeviceStatusLog", back_populates="device")
    alarms = db.relationship("Alarm", back_populates="device")
    alarm_events = db.relationship("AlarmEvent", back_populates="device")
    sleep_sessions = db.relationship("SleepSession", back_populates="device")

class Sensor(db.Model):
    __tablename__ = "sensors"

    id = db.Column(db.Integer, primary_key=True)
    model = db.Column(db.String(100))
    sampling_rate = db.Column(db.Integer)
    status = db.Column(db.String(50))

    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"))
    sensor_type_id = db.Column(db.Integer, db.ForeignKey("sensor_types.id"))

    device = db.relationship("Device", back_populates="sensors")
    sensor_type = db.relationship("SensorType", back_populates="sensors")


class SensorType(db.Model):
    __tablename__ = "sensor_types"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    description = db.Column(db.String(255))

    measurement_unit_id = db.Column(db.Integer, db.ForeignKey("measurement_units.id"))

    measurement_unit = db.relationship("MeasurementUnit", back_populates="sensor_types")
    sensors = db.relationship("Sensor", back_populates="sensor_type")


class MeasurementUnit(db.Model):
    __tablename__ = "measurement_units"

    id = db.Column(db.Integer, primary_key=True)
    unit_name = db.Column(db.String(50))
    symbol = db.Column(db.String(10))

    sensor_types = db.relationship("SensorType", back_populates="measurement_unit")


class DeviceConfiguration(db.Model):
    __tablename__ = "device_configurations"

    id = db.Column(db.Integer, primary_key=True)
    sampling_interval = db.Column(db.Integer)
    data_upload_interval = db.Column(db.Integer)
    sleep_detection_mode = db.Column(db.String(50))
    created_at = db.Column(db.DateTime)

    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"))

    device = db.relationship("Device", back_populates="device_configurations")


class DeviceStatusLog(db.Model):
    __tablename__ = "device_status_logs"

    id = db.Column(db.Integer, primary_key=True)
    battery_level = db.Column(db.Float)
    cpu_temp = db.Column(db.Float)
    wifi_strength = db.Column(db.Integer)
    uptime = db.Column(db.Integer)
    recorded_at = db.Column(db.DateTime)

    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"))

    device = db.relationship("Device", back_populates="device_status_logs")


class Alarm(db.Model):
    __tablename__ = "alarms"

    id = db.Column(db.Integer, primary_key=True)
    alarm_time = db.Column(db.Time)
    enabled = db.Column(db.Boolean)
    smart_wakeup_window = db.Column(db.Integer)
    repeat_days = db.Column(db.String(50))
    created_at = db.Column(db.DateTime)

    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"))

    device = db.relationship("Device", back_populates="alarms")
    alarm_events = db.relationship("AlarmEvent", back_populates="alarm")


class AlarmEvent(db.Model):
    __tablename__ = "alarm_events"

    id = db.Column(db.Integer, primary_key=True)
    triggered_at = db.Column(db.DateTime)
    dismissed_at = db.Column(db.DateTime)
    snoozed = db.Column(db.Boolean)

    alarm_id = db.Column(db.Integer, db.ForeignKey("alarms.id"))
    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"))

    alarm = db.relationship("Alarm", back_populates="alarm_events")
    device = db.relationship("Device", back_populates="alarm_events")


class SleepSession(db.Model):
    __tablename__ = "sleep_sessions"

    id = db.Column(db.Integer, primary_key=True)
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    total_sleep_minutes = db.Column(db.Integer)
    sleep_efficiency = db.Column(db.Float)
    created_at = db.Column(db.DateTime)

    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"))

    device = db.relationship("Device", back_populates="sleep_sessions")
    sleep_scores = db.relationship("SleepScore", back_populates="sleep_session")


class SleepScore(db.Model):
    __tablename__ = "sleep_scores"

    id = db.Column(db.Integer, primary_key=True)
    algorithm_version = db.Column(db.String(50))
    total_score = db.Column(db.Float)
    calculated_at = db.Column(db.DateTime)

    sleep_session_id = db.Column(db.Integer, db.ForeignKey("sleep_sessions.id"))

    sleep_session = db.relationship("SleepSession", back_populates="sleep_scores")
    sleep_metric_scores = db.relationship("SleepMetricScore", back_populates="sleep_score")


class SleepMetricType(db.Model):
    __tablename__ = "sleep_metric_types"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    description = db.Column(db.String(255))

    sleep_metric_scores = db.relationship("SleepMetricScore", back_populates="metric_type")


class SleepMetricScore(db.Model):
    __tablename__ = "sleep_metric_scores"

    id = db.Column(db.Integer, primary_key=True)
    score = db.Column(db.Float)
    raw_value = db.Column(db.Float)

    sleep_score_id = db.Column(db.Integer, db.ForeignKey("sleep_scores.id"))
    metric_type_id = db.Column(db.Integer, db.ForeignKey("sleep_metric_types.id"))

    sleep_score = db.relationship("SleepScore", back_populates="sleep_metric_scores")
    metric_type = db.relationship("SleepMetricType", back_populates="sleep_metric_scores")


class FirmwareVersion(db.Model):
    __tablename__ = "firmware_versions"

    id = db.Column(db.Integer, primary_key=True)
    version_number = db.Column(db.String(50))
    release_date = db.Column(db.DateTime)
    description = db.Column(db.String(255))
    checksum = db.Column(db.String(255))

    devices = db.relationship("Device", back_populates="firmware_version")


class Location(db.Model):
    __tablename__ = "locations"

    id = db.Column(db.Integer, primary_key=True)
    room_name = db.Column(db.String(100))
    building = db.Column(db.String(100))
    timezone = db.Column(db.String(50))
    notes = db.Column(db.String(255))

    devices = db.relationship("Device", back_populates="location")
