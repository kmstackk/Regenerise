import requests

BASE_URL = "https://thingsboard.cs.cf.ac.uk"
USERNAME = "group05@cardiff.ac.uk"
PASSWORD = "ba431gp["


def get_token():
    res = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={
            "username": USERNAME,
            "password": PASSWORD
        }
    )
    res.raise_for_status()
    return res.json()["token"]


def get_latest_telemetry(device_id):
    token = get_token()

    headers = {
        "X-Authorization": f"Bearer {token}"
    }

    res = requests.get(
        f"{BASE_URL}/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries",
        headers=headers,
        params={"keys": "temperature,humidity,light,sound,distance,motion"}
    )
    res.raise_for_status()
    return res.json()
