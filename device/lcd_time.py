import smbus2
import datetime
import time

bus = smbus2.SMBus(1)
LCD_ADDR = 0x3E

def lcd_command(cmd):
    bus.write_byte_data(LCD_ADDR, 0x00, cmd)
    time.sleep(0.0005)

def lcd_write(text):
    for char in text:
        bus.write_byte_data(LCD_ADDR, 0x40, ord(char))

def lcd_init():
    time.sleep(0.05)
    lcd_command(0x38)  # Function set
    lcd_command(0x39)  # Function set
    lcd_command(0x14)  # Internal OSC
    lcd_command(0x70)  # Contrast
    lcd_command(0x56)  # Power/contrast
    lcd_command(0x6C)  # Follower control
    time.sleep(0.2)
    lcd_command(0x38)  # Function set
    lcd_command(0x0C)  # Display on
    lcd_command(0x01)  # Clear display
    time.sleep(0.002)

def lcd_set_cursor(row, col):
    if row == 0:
        lcd_command(0x80 + col)
    else:
        lcd_command(0xC0 + col)

# Get current time
now = datetime.datetime.now()
curr_time = now.strftime("%H:%M")

# Display it
lcd_init()
lcd_set_cursor(0, 0)
lcd_write("Current Time:")
lcd_set_cursor(1, 0)
lcd_write(curr_time)
