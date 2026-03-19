import os
import requests
from flask import Flask, render_template, jsonify
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
from models import (
    db,
)

load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
db.init_app(app)
migrate = Migrate(app, db)

TB_BASE_URL = os.getenv("TB_BASE_URL")
TB_USERNAME = os.getenv("TB_USERNAME")
TB_PASSWORD = os.getenv("TB_PASSWORD")
TB_DEVICE_ID = os.getenv("TB_DEVICE_ID")


def get_token():
    url = f"{TB_BASE_URL}/api/auth/login"
    response = requests.post(
        url,
        json={
            "username": TB_USERNAME,
            "password": TB_PASSWORD
        }
    )
    response.raise_for_status()
    return response.json()["token"]


def get_latest_telemetry():
    token = get_token()
    url = f"{TB_BASE_URL}/api/plugins/telemetry/DEVICE/{TB_DEVICE_ID}/values/timeseries"

    headers = {
        "X-Authorization": f"Bearer {token}"
    }

    params = {
        "keys": "temperature,humidity"
    }

    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data")
def api_data():
    raw = get_latest_telemetry()

    def latest_value(key):
        values = raw.get(key, [])
        if not values:
            return None
        return values[0].get("value")

    return jsonify({
        "temperature": latest_value("temperature"),
        "humidity": latest_value("humidity")
    })


if __name__ == "__main__":
    app.run(debug=True)