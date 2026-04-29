import requests
import datetime

now = datetime.datetime.now()
curr_time = now.strftime("%H:%M")

BASE_URL = "https://thingsboard.cs.cf.ac.uk"
USERNAME = "group05@cardiff.ac.uk"
PASSWORD = "group052026"
DEVICE_ID = "c6f095a0-2df1-11f1-81d7-dd37020598c0"

def get_token():
    res = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": USERNAME, "password": PASSWORD}
    )
    res.raise_for_status()
    return res.json()["token"]

def get_headers():
    token = get_token()
    return {"X-Authorization": f"Bearer {token}"}

# Get alarms
headers = get_headers()
res = requests.get(
    f"{BASE_URL}/api/plugins/telemetry/DEVICE/{DEVICE_ID}/values/attributes/SHARED_SCOPE?keys=alarms",
    headers=headers
)
data = res.json()

# Extract the alarms list
alarms = next((item["value"] for item in data if item["key"] == "alarms"), [])

for alarm in alarms:
    time = alarm[0]
    enabled = alarm[1]
    if enabled and time == curr_time:
        print("True")  # Tell Node-RED to trigger the buzzer
