from grovepi import *
import time

buzzer = 2 


while True:
	digitalWrite(buzzer, 1)
	time.sleep(0.5)
	digitalWrite(buzzer,0)
	time.sleep(0.5)
