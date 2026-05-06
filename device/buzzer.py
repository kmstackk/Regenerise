from grovepi import *
import time

buzzer = 2  # D2
pinMode(buzzer, "OUTPUT")

while True:
    digitalWrite(buzzer, 1)  # On
    time.sleep(0.5)
    digitalWrite(buzzer, 0)  # Off
    time.sleep(0.5)
