import os
import requests
import thingsboard_api
from get_device_data import save_sensor_readings
from flask import Flask, render_template, jsonify
from flask_migrate import Migrate
from dotenv import load_dotenv
from models import (
    db,
)

load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
db.init_app(app)
migrate = Migrate(app, db)

# TODO: switch to a .env - best practice
TB_BASE_URL = os.getenv("TB_BASE_URL")
TB_USERNAME = os.getenv("TB_USERNAME")
TB_PASSWORD = os.getenv("TB_PASSWORD")
TB_DEVICE_ID = os.getenv("TB_DEVICE_ID")


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=True)