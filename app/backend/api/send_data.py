import requests
from thingsboard_api2 import get_valid_token

TB_URL = "https://thingsboard.cs.cf.ac.uk"
DEVICE_ID = "c6f095a0-2df1-11f1-81d7-dd37020598c0"


def get_headers():
    # always get fresh token before making requests

    token = get_valid_token()
    return {
        "X-Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
 
 
def get_alarms() -> list:
    # retrieves the current list of alarms

    url = f"{TB_URL}/api/plugins/telemetry/DEVICE/{DEVICE_ID}/values/attributes/SHARED_SCOPE"
    response = requests.get(url, headers=get_headers())
 
    if response.status_code != 200:
        print(f"Failed to fetch alarms: {response.status_code} {response.text}")
        return []
 
    data = response.json()
    for item in data:
        if item["key"] == "alarms":
            return item["value"]  # already a list
 
    return []  # "alarms" key not set yet
 
 
def push_alarms(alarms: list) -> bool:
    # push alarms to thingsboard

    url = f"{TB_URL}/api/plugins/telemetry/DEVICE/{DEVICE_ID}/attributes/SHARED_SCOPE"
    response = requests.post(url, json={"alarms": alarms}, headers=get_headers())
 
    if response.status_code == 200:
        return True
    else:
        print(f"Failed to push alarms: {response.status_code} {response.text}")
        return False
 
 
def add_alarm(label: str, time: str, enabled: bool=True) -> bool:
    # adds a new alarm to the alarms list, ignores duplicates

    alarms = get_alarms()
 
    if time in alarms:
        print(f"Alarm '{time}' already exists.")
        return False
 
    alarms.append([label, time, enabled])
    alarms.sort()  # keep them in chronological order
 
    success = push_alarms(alarms)
    if success:
        print(f"Alarm added: {time}")
    return success
 
 
def remove_alarm(time: str) -> bool:
    # remove an alarm by its time value, e.g. "07:00"

    alarms = get_alarms()
 
    if time not in alarms:
        print(f"Alarm '{time}' not found. Current alarms: {alarms}")
        return False
 
    alarms.remove(time)
 
    success = push_alarms(alarms)
    if success:
        print(f"Alarm removed: {time}")
    return success
 
 
def clear_alarms() -> bool:
    # remove all alarms at once

    success = push_alarms([])
    if success:
        print("All alarms cleared.")
    return success