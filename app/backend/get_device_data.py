import uuid
from datetime import datetime, timezone
from models import db, Device


def generate_serial_number(prefix="SLP"):
    # format: PREFIX-YYYYMM-XXXXXXXX
    # prefix: identifies product line (e.g. SLP short for "sleep")

    date = datetime.now(timezone.utc).strftime("%Y%m")
    unique_id = uuid.uuid4().hex[:8].upper() # 8 char hex id

    return f"{prefix}-{date}-{unique_id}"


def create_device(device_id):

    device = db.session.get(device_id)

    # check if device is already in the table
    if not device:
        try:
            new_device = Device(
                id = device_id, # PK
                device_name = None,
                device_type = None,
                serial_number = generate_serial_number(),
                status = "active",
                registered_at = datetime.now(timezone.utc),
                last_seen = None,
                location_id = None, # FK
                firmware_version_id = None # FK
            )
            db.session.add(new_device)
            db.session.commit()

        except Exception as e:
            db.session.rollback()
            raise e
        

def get_device_data(device_id):

    pass