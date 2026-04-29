from grovepi import *
import time

buzzer = 7 
pinMode(buzzer, "OUTPUT")
digitalWrite(buzzer, 1)
time.sleep(1)
digitalWrite(buzzer, 0)
