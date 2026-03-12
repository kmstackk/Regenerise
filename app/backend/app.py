import os
import requests
from dotenv import load_dotenv
from flask_migrate import Migrate
from models import (
    db,
    )
load_dotenv()

TOKEN_URL = "https://thingsboard.cs.cf.ac.uk/api/auth/login"
TELEMETRY_URL = "https://thingsboard.cs.cf.ac.uk/api/plugins/telemetry/DEVICE"


def get_token():
    
    # username and pwd are stored in a separate .env file (best practice)
    username = os.getenv("TB_USERNAME")
    password = os.getenv("TB_PASSWORD")

    response = requests.post(TOKEN_URL, json={"username": username,
                                           "password": password})
    
    return response.json()["token"]


def get_keys(device_id, token):

    headers = {"X-Authorization": f"Bearer {token}"}
    url = f"{TELEMETRY_URL}/{device_id}/values/timeseries"

    keys_response = requests.get(url, headers=headers)

# raise an exception if the request failed
    keys_response.raise_for_status()

    keys_json = keys_response.json()
    keys = ",".join(keys_json)

    return keys


def get_telemetry(device_id, keys=""):
    """
    device_id: str
    keys: str ("temperature,humidity,...")
    returns timestamp, value for each key
    """
    token = get_token()
    
    headers = { "X-Authorization": f"Bearer {token}" }
    url = f"{TELEMETRY_URL}/{device_id}/values/timeseries"
    
    # if no keys are specified then get all keys
    if not keys:
        keys = get_keys(device_id, token)
    params = {"keys": keys}

    response = requests.get(url, headers=headers, params=params)

    # raise an exception if the request failed
    response.raise_for_status()

    return response.json()


if __name__ == '__main__':
    # tests - Buzzer Demo Device
    device_id = "74bd9700-0f48-11f1-8ea6-0176c3c84800"
    data = get_telemetry(device_id, "temperature,humidity")
    print(data)