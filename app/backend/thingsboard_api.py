import os
import requests

TOKEN_URL = "https://thingsboard.cloud/api/auth/login"
TELEMETRY_URL = "https://thingsboard.cloud/api/plugins/telemetry/DEVICE"


def get_token():
	
	# username and pwd are stored in a separate .env file (best practice)
	username = os.getenv("USERNAME")
	password = os.getenv("PASSWORD")

	response = requests.post(TOKEN_URL, json={"username": username,
										   "password": password})
	return response.json()["token"]


def get_keys(device_id):

	token = get_token()

	headers = {"X-Authorization": f"Bearer {token}"}
	url = f"{TELEMETRY_URL}/{device_id}/values/timeseries"

	keys_response = requests.get(url, headers=headers)

# raise an exception if the request failed
	keys_response.raise_for_status()

	keys_json = keys_response.json()
	keys = ",".join(keys_json)

	return keys


def get_telemetry(device_id, keys=""):

	token = get_token()
	
	headers = { "X-Authorization": f"Bearer {token}" }
	url = f"{TELEMETRY_URL}/{device_id}/values/timeseries"
	
	# if no keys are specified then get all keys
	if not keys:
		keys = get_keys(device_id)
	params = {"keys": keys}

	response = requests.get(url, headers=headers, params=params)

	# raise an exception if the request failed
	response.raise_for_status()

	return response.json()
