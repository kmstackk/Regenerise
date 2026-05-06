from grovepi import *

button = 2
pinMode(button, "INPUT")

if digitalRead(button) == 1:
	print("STOP")
