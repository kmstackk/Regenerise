import uuid
from datetime import datetime, timezone
from models import db, Device, SensorData


def generate_serial_number(prefix="SLP"):
    date = datetime.now(timezone.utc).strftime("%Y%m")
    unique_id = uuid.uuid4().hex[:8].upper()
    return f"{prefix}-{date}-{unique_id}"


def get_or_create_device(device_id):
    device = db.session.get(Device, device_id)

    if not device:
        try:
            device = Device(
                id=device_id,
                device_name=None,
                device_type=None,
                serial_number=generate_serial_number(),
                status="active",
                registered_at=datetime.now(timezone.utc),
                last_seen=datetime.now(timezone.utc),
                location_id=None,
                firmware_version_id=None
            )
            db.session.add(device)
            db.session.commit()

        except Exception as e:
            db.session.rollback()
            raise e

    else:
        device.last_seen = datetime.now(timezone.utc)
        db.session.commit()

    return device


def save_sensor_readings(device_id, payload):
    device = get_or_create_device(device_id)

    try:
        def get_latest(key, cast_func=None):
            values = payload.get(key, [])
            if not values:
                return None

            raw_value = values[0].get("value")
            if raw_value is None:
                return None

            if cast_func:
                try:
                    return cast_func(raw_value)
                except Exception:
                    return None

            return raw_value

        timestamp = None
        for key in ["temperature", "humidity", "light", "sound", "distance", "motion"]:
            values = payload.get(key, [])
            if values:
                timestamp = values[0].get("ts")
                break

        sensor_data = SensorData(
            timestamp=timestamp,
            temperature=get_latest("temperature", float),
            humidity=get_latest("humidity", float),
            light=get_latest("light", int),
            sound=get_latest("sound", int),
            distance=get_latest("distance", int),
            motion=get_latest("motion", lambda v: str(v).lower() == "true"),
            device=device
        )

        db.session.add(sensor_data)
        db.session.commit()

    except Exception as e:
        db.session.rollback()
        raise e