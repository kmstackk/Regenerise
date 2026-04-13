from dotenv import load_dotenv
import os
import requests

load_dotenv()

TOKEN_URL = os.getenv("TOKEN_URL")
TELEMETRY_URL = os.getenv("TELEMETRY_URL")
TB_DEVICE_ID = os.getenv("TB_DEVICE_ID")
USERNAME = os.getenv("USERNAME")
PASSWORD = os.getenv("PASSWORD")


def get_token():

    response = requests.post(TOKEN_URL, json={"username": USERNAME,
                                           "password": PASSWORD})
    
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


def get_telemetry(device_id=TB_DEVICE_ID, keys=""):
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