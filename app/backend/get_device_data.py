import uuid
from datetime import datetime, timezone
from models import db, Device, SensorData
import thingsboard_api


def generate_serial_number(prefix="SLP"):
    # format: PREFIX-YYYYMM-XXXXXXXX
    # prefix: identifies product line (e.g. SLP short for "sleep")

    date = datetime.now(timezone.utc).strftime("%Y%m")
    unique_id = uuid.uuid4().hex[:8].upper() # 8 char hex id

    return f"{prefix}-{date}-{unique_id}"


def get_or_create_device(device_id):

    device = db.session.get(Device, device_id)

    # check if device is already in the table
    if not device:
        try:
            device = Device(
                id = device_id, # PK
                device_name = None,
                device_type = None,
                serial_number = generate_serial_number(),
                status = "active",
                registered_at = datetime.now(timezone.utc),
                last_seen = datetime.now(timezone.utc),
                location_id = None, # FK
                firmware_version_id = None # FK
            )
            db.session.add(device)
            db.session.commit()

        except Exception as e:
            db.session.rollback()
            raise e
        
    # if device exists, update last_seen
    else:
        device.last_seen = datetime.now(timezone.utc)
        db.session.commit()
    
    return device
        

def save_sensor_readings(device_id, payload):

    device = get_or_create_device(device_id)

    sensor_data = SensorData(
        timestamp = payload["ts"],
        temperature = payload["temperature"],
        humidity = payload["humidity"],
        light = payload["light"],
        sound = payload["sound"],
        distance = payload["distance"],
        motion = payload["motion"],
        
        device=device
    )

    db.session.add(sensor_data)
    db.session.commit()