import requests
import csv
import time

# 🔥 YOUR DETAILS
BASE_URL = "https://thingsboard.cs.cf.ac.uk"
USERNAME = "group05@cardiff.ac.uk"
PASSWORD = "group052026"
DEVICE_ID = "890ce6f0-2386-11f1-81d7-dd37020598c0"

# login once
res = requests.post(f"{BASE_URL}/api/auth/login", json={
    "username": USERNAME,
    "password": PASSWORD
})
token = res.json()["token"]

headers = {
    "X-Authorization": f"Bearer {token}"
}

url = f"{BASE_URL}/api/plugins/telemetry/DEVICE/{DEVICE_ID}/values/timeseries"

# create CSV with header (only once)
with open("data.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["timestamp", "temperature", "humidity"])

print("🚀 Logging started... Press CTRL+C to stop")

while True:
    try:
        res = requests.get(url, headers=headers, params={"keys": "temperature,humidity"})
        data = res.json()

        temp = data.get("temperature", [{}])[0].get("value")
        hum = data.get("humidity", [{}])[0].get("value")
        ts = data.get("temperature", [{}])[0].get("ts")

        # append data
        with open("data.csv", "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([ts, temp, hum])

        print(f"Saved → Temp: {temp}, Humidity: {hum}")

        time.sleep(10)  # ⏱ change this (10 sec)

    except KeyboardInterrupt:
        print("🛑 Stopped logging")
        break

    except Exception as e:
        print("Error:", e)
        time.sleep(5)