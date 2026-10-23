"""Zero Lab sample: two lines on a 16x2 I2C LCD (PCF8574 backpack at 0x27 on I2C1); the second is a live clock."""
import time

try:
    from smbus2 import SMBus
except ImportError:
    from smbus import SMBus

ADDR, RS, EN, BACKLIGHT = 0x27, 0x01, 0x04, 0x08  # PCF8574 pins: P0 RS, P1 RW, P2 E, P3 backlight, P4-P7 D4-D7
bus = SMBus(1)


def nibble(n, rs=0):
    port = (n << 4) | BACKLIGHT | rs
    bus.write_byte(ADDR, port | EN)  # E high, then low: the LCD latches the nibble
    bus.write_byte(ADDR, port)


def send(byte, rs=0):
    nibble(byte >> 4, rs)
    nibble(byte & 0x0F, rs)


def show(row, text):
    send(0x80 | 0x40 * row)  # move to the start of the row
    for ch in text.ljust(16)[:16]:
        send(ord(ch), RS)


for n in (3, 3, 3, 2):  # power-on 8-bit mode -> 4-bit mode
    nibble(n)
    time.sleep(0.005)
for cmd in (0x28, 0x0C, 0x06, 0x01):  # 2 lines, display on (no cursor), move right, clear
    send(cmd)
time.sleep(0.002)
show(0, "Hello, Zero Lab!")
print("Ready: watch the LCD 16x2 widget.", flush=True)
while True:
    clock = time.strftime("%H:%M:%S")
    show(1, clock)
    print(f"clock={clock}", flush=True)
    time.sleep(1 - time.time() % 1)
