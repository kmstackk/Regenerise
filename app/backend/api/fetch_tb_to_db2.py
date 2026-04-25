import time
from models import app
from get_device_data import save_sensor_readings
import thingsboard_api

#access token for device 5a
THINGSBOARD_DEVICE_ID = "c6f095a0-2df1-11f1-81d7-dd37020598c0"
LOCAL_DEVICE_ID = 1

with app.app_context():
    while True:
        try:
            payload = thingsboard_api.get_latest_telemetry(THINGSBOARD_DEVICE_ID)
            save_sensor_readings(LOCAL_DEVICE_ID, payload)
            print("Saved latest telemetry to database")
            time.sleep(10)

        except KeyboardInterrupt:
            print("Stopped")
            break

        except Exception as e:
            print("Error:", e)
            time.sleep(5)
