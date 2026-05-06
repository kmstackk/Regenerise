<h1>Regene<i>rise</i> - GROUP 5 README</h1>

Proforma: 'Explain how you have organised the code, the folder/file structures and any details of 3rd party software and framework you have been using. You need to include sufficient details that a 3rd party can read and understand and set up and replicate your IoT system.'

WE NEED: frontend (Amelia), algorithms (abdul), device code (Calum), ORM code (keyan), API setup (Greg) + more if missing anything

<h2>FRONTEND</h2>
To run the website, navigate to app -> frontend -> initial.py. Run python initial.py in a virtual environment.
The frontend structure is setup with a static folder for all images/icons and the styling page, and a templates folder stores all the html files. Initial.py is what runs the website. Virtual environment with flask needed. 

<h2>API</h2>
The device periodically pushes data to the cloud (thingsboard). The system then generates a token and makes a request (thingsboard REST API) using keys to request specific sensor data (i.e. keys=["motion","distance"] requests readings from the motion and distance sensors).

<h2>DEVICE</h2>
The folder holds the python files used by NodeRed to interact with the button, buzzer, and lcd screen. The files are run through node red when the flow is deployed using the inject nodes.

<h2>App</h2>
Inside the folders backend/api, the python code to push and pull data to and from the raspberry pi is stored. These files allow the device to record the sensor readings and pushes it to the database and also pulls the alarm timings from thingsboard. The files with 2 after were used to test the device overnight on one of the raspberry pis and should be run when testing the device (those without are for the other raspberry pi and were only used for basline data).
