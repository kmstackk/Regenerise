import subprocess
from grovepi import *

subprocess.call(["pkill", "-f", "buzzer.py")

buzzer = 2
pinMode(buzzer, "OUTPUT")
digitalWrite(buzzer, 0)
