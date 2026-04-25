import requests
import time

BASE_URL = "https://thingsboard.cs.cf.ac.uk"
USERNAME = "group05@cardiff.ac.uk"
PASSWORD = "group052026"

# Token state
_token = None
_refresh_token = None
_token_expiry = 0
TOKEN_LIFETIME = 9000       # ThingsBoard JWTs typically last 2.5h; refresh after 2.5h - buffer
TOKEN_REFRESH_BUFFER = 300  # Refresh 5 minutes before expiry


def get_token():
    """Fetch a fresh token and store refresh token + expiry."""
    global _token, _refresh_token, _token_expiry

    res = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": USERNAME, "password": PASSWORD}
    )
    res.raise_for_status()
    data = res.json()

    _token = data["token"]
    _refresh_token = data.get("refreshToken")
    _token_expiry = time.time() + TOKEN_LIFETIME
    return _token


def refresh_token():
    """Use the refresh token to get a new access token without re-logging in."""
    global _token, _refresh_token, _token_expiry

    if not _refresh_token:
        return get_token()

    res = requests.post(
        f"{BASE_URL}/api/auth/token",
        json={"refreshToken": _refresh_token}
    )

    if res.status_code != 200:
        # Refresh token expired or invalid — fall back to full login
        print("Refresh token invalid, re-authenticating...")
        return get_token()

    data = res.json()
    _token = data["token"]
    _refresh_token = data.get("refreshToken", _refresh_token)
    _token_expiry = time.time() + TOKEN_LIFETIME
    return _token


def get_valid_token():
    """Return a valid token, refreshing proactively if close to expiry."""
    global _token, _token_expiry

    if _token is None or time.time() >= (_token_expiry - TOKEN_REFRESH_BUFFER):
        if _token is None:
            get_token()
        else:
            print("Token nearing expiry, refreshing...")
            refresh_token()

    return _token


def get_latest_telemetry(device_id):
    token = get_valid_token()

    headers = {"X-Authorization": f"Bearer {token}"}

    res = requests.get(
        f"{BASE_URL}/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries",
        headers=headers,
        params={"keys": "temperature,humidity,light,sound,distance,motion"}
    )

    # If 401, token may have been invalidated server-side — force refresh and retry once
    if res.status_code == 401:
        print("401 received, forcing token refresh...")
        token = get_token()
        headers = {"X-Authorization": f"Bearer {token}"}
        res = requests.get(
            f"{BASE_URL}/api/plugins/telemetry/DEVICE/{device_id}/values/timeseries",
            headers=headers,
            params={"keys": "temperature,humidity,light,sound,distance,motion"}
        )

    res.raise_for_status()
    return res.json()
