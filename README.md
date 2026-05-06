<h1>Regene<i>rise</i> - GROUP 5 README</h1>

<h2>FRONTEND</h2>
To run the website, navigate to app -> frontend -> initial.py. Run python initial.py in virtual environment.
The frontend structure is setup with a static folder including all images/icons and the css styling page, and a templates folder stores all the html files. Initial.py is what runs the website. Virtual environment with flask needed. 

<h2>API</h2>
The device periodically pushes data to the cloud (thingsboard). The system then generates a token and makes a request (thingsboard REST API) using keys to request specific sensor data (i.e. keys=["motion","distance"] requests readings from the motion and distance sensors).

<h2>DEVICE</h2>
The folder holds the python files used by NodeRed to interact with the button, buzzer, and lcd screen. The files are run through node red when the flow is deployed using the inject nodes.

<h2>APP</h2>
Inside the folders backend/api, the python code to push and pull data to and from the raspberry pi is stored. These files allow the device to record the sensor readings and pushes it to the database and also pulls the alarm timings from thingsboard. The files with 2 after were used to test the device overnight on one of the raspberry pis and should be run when testing the device (those without are for the other raspberry pi and were only used for basline data).

<h2>ORM</h2>
The database for Regenerise is generated using ORM (object relational mapping), using Flask with Flask-SQLAlchemy and SQLite backend. After the models.py file is created accordingly to the ERD, you simply have to install the required dependencies using 'pip install Flask Flask-SQLAlchemy'. You then write a short one line script that calls db.create_all(), and run the file.

<h2>ALGORITHMS</h2>
The hardware layer reads sensor readings written into the database via the thingsboard API. Data is validated and cleaned via processing.py and sleep samples are split into SLEEP/AWAKE/UNCERTAIN in detection.py. Using weighted voting across sensors sleep is scored in scoring.py and data is written back into the database. Alarm manager in algos/alarm.py loads alarm times from database and fires alarm buzzer via GPIO allowing snnooze, dismiss and smart wake up. All thresholds and weights are in config.py and can be changed without editing other code. Used pandas and numpy libraries to facilitate this code 

